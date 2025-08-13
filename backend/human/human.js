const express = require('express');
const fs = require('fs');
const path = require('path');

const Human = require('@vladmandic/human').default;
const tf = require('@tensorflow/tfjs-node');

// ------------ config -------------
const PORT = process.env.PORT || 5002;
const DEFAULT_IMAGES_DIR = path.resolve(__dirname, '..', 'images'); // ../images
const DB_FILE = path.join(__dirname, 'faces-db.json');
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

function loadDB() {
  if (fs.existsSync(DB_FILE)) {
    try {
      facesDB = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
    } catch (e) {
      console.error('[HUMAN] Failed to parse DB, starting fresh:', e.message);
      facesDB = { images: {} };
    }
  }
}

function saveDB() {
  fs.writeFileSync(DB_FILE, JSON.stringify(facesDB, null, 2));
}

loadDB();

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
      name: filename.split('_')[0], // use first part of filename as name (before first underscore)
      path: resolved,
      embeddings,
      enrolledAt: new Date().toISOString()
    };
    saveDB();
    return { added: true, filename, embeddingsCount: embeddings.length };
  }

  // SYNC-DB: scan images dir, add new, remove missing
  app.post('/sync-db', async (req, res) => {
    try {
      const imagesDir = req.body && req.body.imagesDir ? req.body.imagesDir : DEFAULT_IMAGES_DIR;
      const resolvedDir = path.isAbsolute(imagesDir) ? imagesDir : path.resolve(imagesDir);
      if (!fs.existsSync(resolvedDir)) {
        return res.status(400).json({ success: false, message: `imagesDir not found: ${resolvedDir}` });
      }

      const files = fs.readdirSync(resolvedDir).filter(f => {
        const l = f.toLowerCase();
        return l.endsWith('.jpg') || l.endsWith('.jpeg') || l.endsWith('.png') || l.endsWith('.webp');
      });

      // Remove DB entries that don't exist on disk
      const dbFilenames = Object.keys(facesDB.images);
      for (const fn of dbFilenames) {
        const entry = facesDB.images[fn];
        if (!fs.existsSync(entry.path)) {
          delete facesDB.images[fn];
        }
      }

      // Add new files
      let added = 0;
      for (const file of files) {
        const filepath = path.join(resolvedDir, file);
        if (!facesDB.images[file] || facesDB.images[file].path !== filepath) {
          try {
            const r = await processSingleImage(filepath);
            if (r.added) added++;
            else console.warn('[HUMAN] sync: skipped', file, r.reason || '');
          } catch (e) {
            console.warn('[HUMAN] sync error for', file, e.message);
          }
        }
      }

      saveDB();
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
      let { path: probePath, threshold = 0.6, topk = 5 } = req.body || {};
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
            const resolvedDir = DEFAULT_IMAGES_DIR;
            if (fs.existsSync(resolvedDir)) {
              const files = fs.readdirSync(resolvedDir).filter(f => {
                const l = f.toLowerCase();
                return l.endsWith('.jpg') || l.endsWith('.jpeg') || l.endsWith('.png') || l.endsWith('.webp');
              });
              for (const file of files) {
                const filepath = path.join(resolvedDir, file);
                if (!facesDB.images[file]) {
                  try { await processSingleImage(filepath); } catch (e) { /* ignore for sync */ }
                }
              }
            }
            saveDB();
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
        if (filename === probeFilename) continue; // skip itself
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
