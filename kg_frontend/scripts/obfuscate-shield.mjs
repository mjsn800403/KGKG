// prebuild: obfuscate the browser half of the content shield (src/lib/shield.js)
// so its key handling and signing aren't readable in the bundle. Runs in the
// Docker build; rewrites the file in place, so don't run `npm run build` in a
// git checkout you intend to commit from.
import { readFileSync, writeFileSync } from 'node:fs';

const file = new URL('../src/lib/shield.js', import.meta.url);
const MARK = '/*kg-obf*/';
let JO;
try {
  JO = (await import('javascript-obfuscator')).default;
} catch {
  console.log('obfuscate-shield: javascript-obfuscator not installed, skipped');
  process.exit(0);
}
const src = readFileSync(file, 'utf8');
if (src.startsWith(MARK)) process.exit(0);
const out = JO.obfuscate(src, {
  compact: true,
  sourceType: 'module',
  target: 'browser',
  identifierNamesGenerator: 'hexadecimal',
  renameGlobals: false,
  stringArray: true,
  stringArrayEncoding: ['base64'],
  stringArrayThreshold: 1,
  controlFlowFlattening: true,
  controlFlowFlatteningThreshold: 0.5,
  deadCodeInjection: false,
  selfDefending: false,
}).getObfuscatedCode();
writeFileSync(file, MARK + out);
console.log(`obfuscate-shield: ${src.length} -> ${out.length} bytes`);
