const express = require('express');
const fs = require('fs');
const path = require('path');

const Human = require('@vladmandic/human').default;
const tf = require('@tensorflow/tfjs-node');

// ------------ config -------------
const PORT = process.env.PORT || 5002;
const DEFAULT_IMAGES_DIR = path.resolve(__dirname, '..', 'images'); // ../images
const DEFAULT_DB_FILE = path.join(__dirname, 'faces-db.json');
let DB_FILE = path.join(__dirname, 'faces-db.json');
// ----------------------------------

// Minimal DB structure:
// {
//   images: {
//     "<filename>": {
//        name: "<personToken>",
//        path: "/abs/path/to/file",
//        embeddings: [ [float,...], [float,...] ],  // one array per detected face in that image
//        enrolledAt: "ISO timestamp"
//     },
//     ...
//   }
// }
let facesDB = { images: {} };

function resolveDbFile(dbFileOrName) {
  if (!dbFileOrName) return DB_FILE;
  let f = dbFileOrName;
  if (!f.endsWith('.json')) f = `${f}.json`;
  if (!path.isAbsolute(f)) f = path.join(__dirname, f);
  return f;
}

function loadDBFile(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf8');
      return JSON.parse(raw);
    }
  } catch (e) {
    console.error('[HUMAN] Failed to parse DB', filePath, 'starting fresh:', e.message);
  }
  return { images: {} };
}

function saveDBFile(filePath, dbObj) {
  try {
    fs.writeFileSync(filePath, JSON.stringify(dbObj, null, 2));
  } catch (e) {
    console.error('[HUMAN] Failed to save DB', filePath, e.message);
  }
}

function switchDB(dbFileOrName) {
  const next = resolveDbFile(dbFileOrName);
  DB_FILE = next;
  facesDB = loadDBFile(DB_FILE);
}

// init default DB
facesDB = loadDBFile(DB_FILE);

const human = new Human({
  modelBasePath: 'https://cdn.jsdelivr.net/npm/@vladmandic/human/models/',
  cacheSensitivity: 0,
  face: {
    enabled: true,
    detector: { rotation: true, return: true },
    mesh: { enabled: true },
    description: { enabled: true },
    embedding: { enabled: true },
  },
  logger: 'verbose'
});

function getNameFromFilename(filename) {
  // Extract name from filename (before numbers)
  const match = filename.match(/^(.*?)(_\d+)?\.(jpg|jpeg|png|webp)$/i);
  return match ? match[1] : filename;
}

// We stick to filename-derived names: <Name>_123.jpg -> <Name>
function getNameFromPath(filePath) {
  return getNameFromFilename(path.basename(filePath));
}

function listImageFilesRecursive(rootDir) {
  const out = [];
  const stack = [rootDir];
  while (stack.length) {
    const cur = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(cur, { withFileTypes: true });
    } catch (e) {
      continue;
    }
    for (const ent of entries) {
      const p = path.join(cur, ent.name);
      if (ent.isDirectory()) stack.push(p);
      else if (ent.isFile()) {
        const l = ent.name.toLowerCase();
        if (l.endsWith('.jpg') || l.endsWith('.jpeg') || l.endsWith('.png') || l.endsWith('.webp')) out.push(p);
      }
    }
  }
  return out;
}

(async () => {
  await human.init();
  console.log('[HUMAN] initialized');

  const app = express();
  app.use(express.json({ limit: '10mb' }));

  // Utility: compute embeddings from image file path
  async function computeEmbeddingsFromPath(imagePath) {
    const resolved = path.isAbsolute(imagePath) ? imagePath : path.resolve(imagePath);
    if (!fs.existsSync(resolved)) {
      throw new Error(`File not found: ${resolved}`);
    }
    const buffer = fs.readFileSync(resolved);
    const imgTensor = tf.node.decodeImage(buffer, 3);       // decode -> Tensor3D (H x W x 3)
    const result = await human.detect(imgTensor);        // pass Tensor to human.detect
    imgTensor.dispose();
    
    if (!result || !result.face || result.face.length === 0) return [];
    // collect embeddings for all detected faces
    const embs = result.face.map(f => {
      const e = f.embedding || f.descriptor || null;
      return e ? Array.from(e) : null;
    }).filter(Boolean);
    return embs; // array of arrays (one per face)
  }

  // Sync single image into DB (compute embeddings and add)
  async function processSingleImage(filepath) {
    const resolved = path.isAbsolute(filepath) ? filepath : path.resolve(filepath);
    if (!fs.existsSync(resolved)) {
      throw new Error(`File not found: ${resolved}`);
    }
    const filename = path.basename(resolved);

    const embeddings = await computeEmbeddingsFromPath(resolved);
    if (!embeddings || embeddings.length === 0) {
      // No faces found - return info but do not add to DB
      return { added: false, reason: 'no-face' };
    }

    facesDB.images[filename] = {
      name: getNameFromPath(resolved), // prefer folder name (dataset person) else filename stem
      path: resolved,
      embeddings,
      enrolledAt: new Date().toISOString()
    };
    saveDBFile(DB_FILE, facesDB);
    return { added: true, filename, embeddingsCount: embeddings.length };
  }

  // SYNC-DB: scan images dir, add new, remove missing
  app.post('/sync-db', async (req, res) => {
    try {
        const imagesDir = req.body && req.body.imagesDir ? req.body.imagesDir : DEFAULT_IMAGES_DIR;
        const dbFileArg = (req.body && (req.body.dbFile || req.body.datasetName)) || null;
        if (dbFileArg) {
        const name = req.body.datasetName ? `${req.body.datasetName}_faces-db.json` : dbFileArg;
          switchDB(name);
        } else {
          switchDB(DEFAULT_DB_FILE);
        }
        const resolvedDir = path.isAbsolute(imagesDir) ? imagesDir : path.resolve(imagesDir);
        if (!fs.existsSync(resolvedDir)) {
        return res.status(400).json({ success: false, message: `imagesDir not found: ${resolvedDir}` });
        }

        let files = [];
        let filePersonPairs = [];

        if (req.body && req.body.personNames && Array.isArray(req.body.personNames)) {
        // For each person name, find all matching files in imagesDir
        const personNames = req.body.personNames;
        const allFiles = listImageFilesRecursive(resolvedDir);

        // Build regex for each person name and collect matches
        for (const name of personNames) {
            // Match: name_somenumber.{jpg,png,webp,jpeg} or name_cloaked_{low,mid,high}.{jpg,png,webp,jpeg}
            const regex = new RegExp(`^${name}(_\\d+)?(_cloaked_(low|mid|high))?\\.(jpg|jpeg|png|webp)$`, 'i');
            for (const filePath of allFiles) {
            const base = path.basename(filePath);
            if (regex.test(base)) {
            filePersonPairs.push({ filePath, personName: name });
            }
            }
        }
        files = filePersonPairs;
        } else {
        // Default: all files, person name from filename
        const allFiles = listImageFilesRecursive(resolvedDir);
        files = allFiles.map(filePath => ({
            filePath,
            personName: getNameFromFilename(path.basename(filePath))
        }));
        }

        // Remove DB entries that aren't in files array
        const validFileSet = new Set(files.map(f => path.basename(f.filePath)));
        for (const fn of Object.keys(facesDB.images)) {
        if (!validFileSet.has(fn)) {
            delete facesDB.images[fn];
        }
        }

        // Add new files
        let added = 0;
        for (const { filePath, personName } of files) {
        const file = path.basename(filePath);
        if (!facesDB.images[file] || facesDB.images[file].path !== filePath) {
            try {
            // processSingleImage will use getNameFromPath, but we want to override with personName
            const embeddings = await computeEmbeddingsFromPath(filePath);
            if (!embeddings || embeddings.length === 0) {
            console.warn('[HUMAN] sync: skipped', file, 'no-face');
            continue;
            }
            facesDB.images[file] = {
            name: personName,
            path: filePath,
            embeddings,
            enrolledAt: new Date().toISOString()
            };
            added++;
            console.log('[HUMAN] sync: added', file, 'as', personName);
            } catch (e) {
            console.warn('[HUMAN] sync error for', file, e.message);
            }
        }
        }

    //   // Remove DB entries that don't exist on disk
    //   const dbFilenames = Object.keys(facesDB.images);
    //   for (const fn of dbFilenames) {
    //     const entry = facesDB.images[fn];
    //     if (!fs.existsSync(entry.path)) {
    //       delete facesDB.images[fn];
    //     }
    //   }

    //   // Add new files
    //   let added = 0;
    //   for (const filepath of files) {
    //     const file = path.basename(filepath);
    //     if (!facesDB.images[file] || facesDB.images[file].path !== filepath) {
    //       try {
    //         const r = await processSingleImage(path.join(imagesDir, filename));
    //         if (r.added) added++;
    //         else console.warn('[HUMAN] sync: skipped', file, r.reason || '');
    //       } catch (e) {
    //         console.warn('[HUMAN] sync error for', file, e.message);
    //       }
    //     }
    //   }

        saveDBFile(DB_FILE, facesDB);
        return res.json({ success: true, message: 'sync complete', added, total: Object.keys(facesDB.images).length });
    } catch (err) {
        console.error('[HUMAN] /sync-db error:', err);
        return res.status(500).json({ success: false, message: err.message });
    }
  });

  // ENROLL: just process the given path (delegates to same logic as sync)
  // Expected body: { path: "/abs/or/relative/path/to/image.jpg" }
  app.post('/enroll', async (req, res) => {
    try {
      const imagePath = req.body && req.body.path;
      const dbFileArg = (req.body && (req.body.dbFile || req.body.datasetName)) || null;
      if (dbFileArg) {
        const name = req.body.datasetName ? `${req.body.datasetName}_faces-db.json` : dbFileArg;
        switchDB(name);
      }
      if (!imagePath) return res.status(400).json({ success: false, message: 'Missing path' });
      const r = await processSingleImage(imagePath);
      if (!r.added) return res.status(400).json({ success: false, message: 'No face found or image skipped', reason: r.reason });
      return res.json({ success: true, filename: r.filename, embeddingsCount: r.embeddingsCount });
    } catch (err) {
      console.error('[HUMAN] /enroll error:', err);
      return res.status(500).json({ success: false, message: err.message });
    }
  });

  // LIST enrolled images (debug)
  app.get('/list-enrolled', (req, res) => {
    const dbFileArg = req.query && (req.query.dbFile || req.query.datasetName);
    if (dbFileArg) {
      const name = req.query.datasetName ? `${req.query.datasetName}_faces-db.json` : dbFileArg;
      switchDB(name);
    }
    const list = Object.entries(facesDB.images).map(([filename, entry]) => ({
      filename,
      name: entry.name,
      path: entry.path,
      embeddings: (entry.embeddings || []).length,
      enrolledAt: entry.enrolledAt
    }));
    return res.json({ success: true, total: list.length, images: list });
  });

  // MATCH: { path: "/path/to/probe.jpg" OR filename, threshold: 0.6, topk: 5 }
  app.post('/match', async (req, res) => {
    try {
      let { path: probePath, threshold = 0.6, topk = 5, dbFile, datasetName, imagesDir } = req.body || {};
      if (dbFile || datasetName) {
        const name = datasetName ? `${datasetName}_faces-db.json` : dbFile;
        switchDB(name);
      }
      if (!probePath) return res.status(400).json({ success: false, message: 'Missing path' });
      threshold = parseFloat(threshold);
      topk = parseInt(topk, 10) || 5;

      // Ensure DB is synced (so embeddings exist)
      await new Promise((resolve, reject) => {
        // call internal sync using default images dir
        // We prefer to call the function directly rather than HTTP to avoid race conditions
        // Here we run the same logic as sync: scan DEFAULT_IMAGES_DIR and add missing entries
        (async () => {
          try {
            // Quick internal sync: add any missing files from DEFAULT_IMAGES_DIR
            const resolvedDir = imagesDir ? (path.isAbsolute(imagesDir) ? imagesDir : path.resolve(imagesDir)) : DEFAULT_IMAGES_DIR;
            if (fs.existsSync(resolvedDir)) {
              const files = listImageFilesRecursive(resolvedDir);
              for (const filepath of files) {
                const file = path.basename(filepath);
                if (!facesDB.images[file]) {
                  try { await processSingleImage(filepath); } catch (e) { /* ignore for sync */ }
                }
              }
            }
            saveDBFile(DB_FILE, facesDB);
            resolve();
          } catch (e) { reject(e); }
        })();
      });

      const resolvedProbe = path.isAbsolute(probePath) ? probePath : path.resolve(probePath);
      if (!fs.existsSync(resolvedProbe)) {
        return res.status(400).json({ success: false, message: `Probe file not found: ${resolvedProbe}` });
      }

      // Ensure probe is embedded in DB (so that matching uses same embedding process)
      const probeFilename = path.basename(resolvedProbe);
      if (!facesDB.images[probeFilename] || !facesDB.images[probeFilename].embeddings || facesDB.images[probeFilename].embeddings.length === 0) {
        try {
          await processSingleImage(resolvedProbe);
        } catch (e) {
          return res.status(400).json({ success: false, message: `Probe embedding failed: ${e.message}` });
        }
      }

      const probeEntry = facesDB.images[probeFilename];
      if (!probeEntry) return res.status(500).json({ success: false, message: 'Probe embedding missing after processing' });
      const probeEmbs = probeEntry.embeddings; // array of embeddings (arrays)

      // Now compare probe embeddings to every other image's embeddings (skip itself)
      const results = []; // { filename, name, similarity }
      for (const [filename, entry] of Object.entries(facesDB.images)) {
        if (filename == probeFilename) continue; // skip itself
        if (!entry.embeddings || entry.embeddings.length === 0) continue;
        // compute best similarity across all face pairs (probe faces vs db faces)
        let bestSim = -1;
        for (const p of probeEmbs) {
          for (const e of entry.embeddings) {
            // human.match.similarity expects arrays or typed arrays
            const sim = human.match.similarity(p, e);
            if (sim > bestSim) bestSim = sim;
          }
        }
        if (bestSim >= threshold) {
          results.push({ filename, name: entry.name, similarity: bestSim });
        }
      }

      // sort by similarity desc and return topk
      results.sort((a, b) => b.similarity - a.similarity);
      return res.json({ success: true, probe: probeFilename, matches: results.slice(0, topk) });
    } catch (err) {
      console.error('[HUMAN] /match error:', err);
      return res.status(500).json({ success: false, message: err.message });
    }
  });

  app.get('/health', (req, res) => res.json({ ok: true }));

  app.listen(PORT, () => {
    console.log(`[HUMAN] listening on ${PORT}, DB file: ${DB_FILE}`);
    // create default images dir if not exists
    try { fs.mkdirSync(DEFAULT_IMAGES_DIR, { recursive: true }); } catch (e) {}
  });
})();
