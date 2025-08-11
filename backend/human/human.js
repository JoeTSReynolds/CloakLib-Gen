// human/human.js
// Simple Human server that computes embeddings from local image files
// Endpoints:
//  POST /enroll       { name: string, path: string }   -> compute embedding & store
//  POST /match        { path: string, topk?: number }  -> compute embedding & return top matches
//  POST /sync-db      { imagesDir: string }            -> scan imagesDir and ensure DB has embeddings

const express = require('express');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');

// IMPORTANT: load tfjs-node before human so native backend is used
try {
  require('@tensorflow/tfjs-node'); // or tfjs-node-gpu if installed
} catch (e) {
  console.warn('[HUMAN] Warning loading @tensorflow/tfjs-node (maybe you run in pure JS backend):', e.message);
}

// dynamic import of Human
(async () => {
  const humanMod = await import('@vladmandic/human');
  // module may export class as `Human` (named) or as default
  const HumanClass = humanMod.Human || humanMod.default;
  if (typeof HumanClass !== 'function') {
    console.error('[HUMAN] Could not find Human constructor. Module exports:', Object.keys(humanMod));
    console.error('[HUMAN] humanMod.default type:', typeof humanMod.default);
    process.exit(1);
  }

  const PORT = process.env.PORT || 5002;
  const DB_FILE = path.join(__dirname, 'faces-db.json');

  const app = express();
  app.use(bodyParser.json({ limit: '10mb' }));

  // load or init DB
  let facesDB = { people: {} };
  function saveDB() {
    fs.writeFileSync(DB_FILE, JSON.stringify(facesDB, null, 2));
  }
  function loadDB() {
    if (fs.existsSync(DB_FILE)) {
      try {
        facesDB = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
      } catch (e) {
        console.error('[HUMAN] Failed to parse DB, starting fresh:', e);
        facesDB = { people: {} };
      }
    }
  }
  loadDB();

  const human = new HumanClass({
    modelBasePath: 'https://cdn.jsdelivr.net/npm/@vladmandic/human/models/',
    cacheSensitivity: 0,
    face: {
      enabled: true,
      detector: { enabled: true },
      description: { enabled: true },
      embedding: { enabled: true },
    },
    // logger: 'verbose' // enable if you want more logs
  });
  await human.init();
  console.log('[HUMAN] Human initialized');

  // helper cosine similarity
  function cosineSimilarity(a, b) {
    let dot = 0;
    let na = 0;
    let nb = 0;
    for (let i = 0; i < a.length; i++) {
      dot += a[i] * b[i];
      na += a[i] * a[i];
      nb += b[i] * b[i];
    }
    if (na === 0 || nb === 0) return 0;
    return dot / (Math.sqrt(na) * Math.sqrt(nb));
  }

  // compute embedding from local file path or Buffer
  async function computeEmbeddingFromPath(imagePath) {
    if (!fs.existsSync(imagePath)) {
      throw new Error(`File not found: ${imagePath}`);
    }
    const buf = fs.readFileSync(imagePath);
    // human.detect accepts Buffer in Node
    const result = await human.detect(buf);
    if (!result || !result.face || result.face.length === 0) {
      return null;
    }
    // take first face
    const emb = result.face[0].embedding || result.face[0].descriptor;
    if (!emb) return null;
    // convert Float32Array -> Array for JSON storage
    return Array.from(emb);
  }

  // ENROLL: { name, path }
  app.post('/enroll', async (req, res) => {
    try {
      const { name, path: imagePath } = req.body;
      if (!name || !imagePath) {
        return res.status(400).json({ success: false, message: 'Missing name or path' });
      }
      const resolvedPath = path.isAbsolute(imagePath) ? imagePath : path.resolve(imagePath);
      if (!fs.existsSync(resolvedPath)) {
        return res.status(400).json({ success: false, message: `File does not exist: ${resolvedPath}` });
      }
      const emb = await computeEmbeddingFromPath(resolvedPath);
      if (!emb) {
        return res.status(400).json({ success: false, message: 'No face found in image' });
      }

      if (!facesDB.people[name]) {
        facesDB.people[name] = { embeddings: [], images: [], enrolledAt: new Date().toISOString() };
      }
      facesDB.people[name].embeddings.push(emb);
      facesDB.people[name].images.push(resolvedPath);
      facesDB.people[name].enrolledAt = new Date().toISOString();
      saveDB();

      return res.json({ success: true, name, embeddingLength: emb.length });
    } catch (err) {
      console.error('[HUMAN] /enroll error:', err);
      return res.status(500).json({ success: false, message: err.message });
    }
  });

  // MATCH: { path, topk }
  app.post('/match', async (req, res) => {
    try {
      const { path: imagePath, topk = 5 } = req.body;
      if (!imagePath) return res.status(400).json({ success: false, message: 'Missing path' });
      const resolvedPath = path.isAbsolute(imagePath) ? imagePath : path.resolve(imagePath);
      if (!fs.existsSync(resolvedPath)) {
        return res.status(400).json({ success: false, message: `File does not exist: ${resolvedPath}` });
      }

      const probeEmb = await computeEmbeddingFromPath(resolvedPath);
      if (!probeEmb) {
        return res.status(400).json({ success: false, message: 'No face found in probe image' });
      }

      // iterate DB and compute best similarities
      const matches = []; // { name, similarity, imagePath, index }
      for (const [name, entry] of Object.entries(facesDB.people)) {
        const embeddings = entry.embeddings || [];
        for (let i = 0; i < embeddings.length; i++) {
          const sim = cosineSimilarity(probeEmb, embeddings[i]);
          matches.push({ name, similarity: sim, imagePath: entry.images[i] || null, index: i });
        }
      }

      // sort desc (largest similarity first)
      matches.sort((a, b) => b.similarity - a.similarity);

      return res.json({ success: true, probeEmbeddingLength: probeEmb.length, matches: matches.slice(0, topk) });
    } catch (err) {
      console.error('[HUMAN] /match error:', err);
      return res.status(500).json({ success: false, message: err.message });
    }
  });

  // SYNC-DB: { imagesDir }
  // Scans imagesDir for filenames like <person>_*.jpg and enrolls any that aren't present in DB
  app.post('/sync-db', async (req, res) => {
    try {
      const imagesDir = req.body.imagesDir;
      if (!imagesDir) return res.status(400).json({ success: false, message: 'Missing imagesDir' });
      const resolvedDir = path.isAbsolute(imagesDir) ? imagesDir : path.resolve(imagesDir);
      if (!fs.existsSync(resolvedDir)) return res.status(400).json({ success: false, message: `Dir not found: ${resolvedDir}` });

      const files = fs.readdirSync(resolvedDir).filter(f => {
        const l = f.toLowerCase();
        return l.endsWith('.jpg') || l.endsWith('.jpeg') || l.endsWith('.png') || l.endsWith('.webp');
      });

      let added = 0;
      for (const file of files) {
        const filepath = path.join(resolvedDir, file);
        // parse name before first underscore
        const base = path.basename(file);
        const name = base.includes('_') ? base.split('_')[0] : path.parse(base).name;
        // if not present or if filepath not in images list, enroll
        if (!facesDB.people[name] || !facesDB.people[name].images.includes(filepath)) {
          try {
            const emb = await computeEmbeddingFromPath(filepath);
            if (!emb) {
              console.warn('[HUMAN] sync: no face in', filepath);
              continue;
            }
            if (!facesDB.people[name]) facesDB.people[name] = { embeddings: [], images: [], enrolledAt: new Date().toISOString() };
            facesDB.people[name].embeddings.push(emb);
            facesDB.people[name].images.push(filepath);
            facesDB.people[name].enrolledAt = new Date().toISOString();
            added++;
          } catch (e) {
            console.warn('[HUMAN] sync error for', filepath, e.message);
          }
        }
      }

      saveDB();
      return res.json({ success: true, message: 'Sync complete', added, total: Object.keys(facesDB.people).length });
    } catch (err) {
      console.error('[HUMAN] /sync-db error:', err);
      return res.status(500).json({ success: false, message: err.message });
    }
  });

  // small health endpoint
  app.get('/health', (req, res) => res.json({ ok: true }));

  app.listen(PORT, () => {
    console.log(`[HUMAN] Server listening on ${PORT}. DB: ${DB_FILE}`);
  });
})();
