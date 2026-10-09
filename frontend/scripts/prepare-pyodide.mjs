import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const source = join(root, "node_modules/pyodide");
const destination = join(root, "public/pyodide");
const { version } = JSON.parse(await readFile(join(source, "package.json"), "utf8"));
const lock = JSON.parse(await readFile(join(source, "pyodide-lock.json"), "utf8"));
const base = `https://cdn.jsdelivr.net/pyodide/v${version}/full/`;
await mkdir(destination, { recursive: true });
for (const file of ["pyodide.asm.wasm", "pyodide.asm.mjs", "python_stdlib.zip", "pyodide-lock.json", "pyodide.mjs"]) {
  await copyFile(join(source, file), join(destination, file));
}

// Ship the standard science libraries with the app. First use must not depend on a CDN.
// Other Pyodide packages can still be fetched on demand.
const packages = new Set();
function include(name) {
  if (packages.has(name)) return;
  packages.add(name);
  for (const dependency of lock.packages[name].depends) include(dependency);
}
["numpy", "pandas", "matplotlib", "scipy"].forEach(include);
const digest = (data) => createHash("sha256").update(data).digest("hex");
await Promise.all(Array.from(packages, async (name) => {
  const pkg = lock.packages[name];
  const target = join(destination, pkg.file_name);
  try {
    if (digest(await readFile(target)) === pkg.sha256) return;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  console.log(`Preparing Python package: ${name}`);
  const response = await fetch(base + pkg.file_name, { signal: AbortSignal.timeout(600_000) });
  if (!response.ok) throw new Error(`Downloading ${name}: HTTP ${response.status}`);
  const data = Buffer.from(await response.arrayBuffer());
  if (digest(data) !== pkg.sha256) throw new Error(`Checksum mismatch for ${name}`);
  await writeFile(`${target}.part`, data);
  await rename(`${target}.part`, target);
}));

// Keep nonstandard packages available from the matching release, while resolving all
// bundled wheels locally. Pyodide accepts absolute URLs in its lockfile.
for (const [name, pkg] of Object.entries(lock.packages)) {
  if (!packages.has(name)) pkg.file_name = base + pkg.file_name;
}
await writeFile(join(destination, "pyodide-lock.json"), JSON.stringify(lock));
console.log(`Python ${version} and ${packages.size} packages ready.`);
