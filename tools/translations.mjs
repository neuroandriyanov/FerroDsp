// No dependencies or network. Russian publication never waits for a translation.
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { resolve, relative, sep } from 'node:path';
import { createHash } from 'node:crypto';

const root = process.cwd();
const manifestPath = resolve(root, 'translations.json');
const digest = path => createHash('sha256').update(readFileSync(resolve(root, path))).digest('hex');
const manifest = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : {version:1, sourceLanguage:'ru', targetLanguage:'en', entries:[]};
const [command = 'status', ...args] = process.argv.slice(2);
const safe = path => {
  const absolute = resolve(root, path);
  if (!absolute.startsWith(root + sep) || path.split(/[\\/]/).includes('.git')) throw new Error(`Path outside content workspace: ${path}`);
  return relative(root, absolute).replaceAll('\\', '/');
};

if (command === 'record') {
  if (args.length !== 2) throw new Error('Usage: node tools/translations.mjs record source target');
  const [source, target] = args.map(safe);
  if (source === target) throw new Error('Source and translation must be different files');
  const entry = {source, target, sourceSha256:digest(source), targetSha256:digest(target)};
  manifest.entries = [...manifest.entries.filter(e => e.source !== source || e.target !== target), entry].sort((a,b) => a.source.localeCompare(b.source));
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  console.log(`Recorded reviewed translation: ${source} -> ${target}`);
} else if (command === 'status') {
  const ignored = new Set(['.git','.translation-work','node_modules','dist','.astro','.wrangler','.venv','venv','__pycache__','tmp','output','captures','Drivers','vendor','third_party']);
  const discovered = [];
  function scan(dir) {
    if (!existsSync(dir)) return;
    for (const item of readdirSync(dir, {withFileTypes:true})) {
      const path = resolve(dir, item.name);
      if (item.isSymbolicLink()) continue;
      if (item.isDirectory()) { if (!ignored.has(item.name) && !item.name.startsWith('.')) scan(path); continue; }
      const local = relative(root, path).replaceAll('\\','/');
      if (!/\.md$/i.test(item.name) || /\.en\.md$/i.test(item.name) || /(?:^|\/)en\//.test(local) || (manifest.excludedSources ?? []).includes(local)) continue;
      if (/[А-Яа-яЁё]/u.test(readFileSync(path,'utf8'))) discovered.push(local);
    }
  }
  for (const base of manifest.sourceRoots ?? ['.']) scan(resolve(root, safe(base === '.' ? './README.md' : base), base === '.' ? '..' : '.'));
  const sources = new Set(manifest.entries.map(e=>safe(e.source)));
  const counts = {current:0, stale:0, changed:0, missing:0, broken:0};
  for (const entry of manifest.entries) {
    const source = safe(entry.source), target = safe(entry.target);
    let status = 'current';
    if (!existsSync(resolve(root, source)) || !existsSync(resolve(root, target))) status = 'broken';
    else if (digest(source) !== entry.sourceSha256) status = 'stale';
    else if (entry.targetSha256 && digest(target) !== entry.targetSha256) status = 'changed';
    counts[status]++;
    if (status !== 'current' || args.includes('--all')) console.log(`${status.toUpperCase()} ${source} -> ${target}`);
  }
  for (const source of discovered.filter(p => !sources.has(p))) { counts.missing++; console.log(`MISSING ${source}`); }
  console.log(JSON.stringify(counts));
  if (counts.broken || (args.includes('--strict') && (counts.stale || counts.changed || counts.missing))) process.exitCode = 1;
} else throw new Error('Use status [--all] [--strict] or record source target');
