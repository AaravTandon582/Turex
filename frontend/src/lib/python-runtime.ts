/**
 * Python, running in this browser tab.
 *
 * Turex could describe an experiment but not do one, so every number a researcher computed
 * came from somewhere else and arrived as a sentence typed into a form. This closes that gap
 * without opening the one that usually comes with it.
 *
 * **Nothing executes on the server.** The interpreter is CPython compiled to WebAssembly,
 * running inside the browser's own sandbox: no filesystem beyond a virtual one, no network
 * except what the page could already reach, no access to the host. Running code a user
 * supplies is the most dangerous thing a web application can do, and the only version of it
 * worth shipping is the one where the untrusted code never reaches a machine you own. The
 * server's entire involvement is storing the text that comes back.
 *
 * Loading costs about 13MB, which is why it happens on demand — when someone runs a cell,
 * not when they open the page — and once per tab thereafter.
 */

import type { PyodideInterface } from "pyodide";

export interface RunResult {
  /** Everything the cell printed, plus the value of its final expression. */
  output: string;
  /** A matplotlib figure as a PNG data URI, if the cell drew one. */
  image: string | null;
  /** A traceback, trimmed to the part about the user's code. */
  error: string | null;
  durationMs: number;
}

export type RuntimeStage = "idle" | "loading" | "ready" | "failed";

/**
 * The Pyodide release whose wheels match the interpreter served from `/pyodide/`.
 *
 * Must equal the `pyodide` version in package.json. A mismatch fetches wheels built against a
 * different ABI, which fails at import with an error that never mentions versions — so
 * `e2e/workstation.spec.ts` asserts the two agree rather than leaving it to be noticed later.
 */
export const PYODIDE_VERSION = "314.0.5";

/** The packages worth having before the first cell runs. */
const PRELOAD = ["numpy", "pandas", "matplotlib", "scipy"] as const;

/**
 * Where the interpreter's own module lives, served from `public/`.
 *
 * Held in a variable rather than written inline so TypeScript does not try to resolve it: an
 * absolute path is not a module specifier it can follow, and an ambient `declare module` does
 * not apply to one either. The bundler comments on the import are what actually matter, and
 * they apply to the expression however the specifier is spelled.
 */
const RUNTIME_MODULE = "/pyodide/pyodide.mjs";

/**
 * Capture stdout, run the source, and render the last expression the way a REPL would.
 *
 * Written as Python rather than assembled in TypeScript because it has to behave like a
 * notebook cell: statements run for their effect, and a trailing *expression* also shows its
 * value. `ast` is the only honest way to tell those apart — splitting on newlines and
 * guessing gets `x = [1,\n2]` wrong immediately.
 */
const HARNESS = `
import ast, base64, io, sys, traceback

def __turex_run(source, namespace):
    stdout, stderr = io.StringIO(), io.StringIO()
    image = None
    error = None

    try:
        parsed = ast.parse(source)
    except SyntaxError:
        return {"output": "", "image": None, "error": traceback.format_exc(limit=0)}

    # A trailing expression is compiled separately in 'single' mode so its value is echoed,
    # which is the behaviour that makes a notebook feel like a REPL rather than a script.
    tail = None
    if parsed.body and isinstance(parsed.body[-1], ast.Expr):
        tail = ast.Interactive(body=[parsed.body.pop()])

    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        exec(compile(parsed, "<cell>", "exec"), namespace)
        if tail is not None:
            exec(compile(tail, "<cell>", "single"), namespace)
    except BaseException:
        # The first two frames are this harness. Hiding them keeps the traceback about the
        # user's own code, which is the only part they can act on.
        error = "".join(traceback.format_exception(*sys.exc_info())[2:])
    finally:
        sys.stdout, sys.stderr = real_out, real_err

    # A figure is the output most worth keeping and the one that cannot survive as text.
    # Drained after every run so the next cell does not re-emit this one's plot.
    if "matplotlib.pyplot" in sys.modules:
        plt = sys.modules["matplotlib.pyplot"]
        if plt.get_fignums():
            buffer = io.BytesIO()
            plt.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
            image = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
            plt.close("all")

    return {
        "output": stdout.getvalue() + stderr.getvalue(),
        "image": image,
        "error": error,
    }
`;

let runtime: PyodideInterface | null = null;
let loading: Promise<PyodideInterface> | null = null;

/**
 * Load the interpreter, once per tab.
 *
 * The promise is cached rather than the result, so two cells run in quick succession share one
 * download instead of racing two.
 */
export function loadRuntime(onProgress?: (message: string) => void): Promise<PyodideInterface> {
  if (runtime) return Promise.resolve(runtime);
  if (loading) return loading;

  loading = (async () => {
    onProgress?.("Downloading Python…");

    // Loaded from our own `/pyodide/` at runtime rather than imported from `node_modules`.
    //
    // Bundling it does not work: the package resolves its own assets with expressions the
    // bundler cannot follow, and `await import("pyodide")` fails at runtime with "Cannot find
    // module as expression is too dynamic" — a message that says nothing about the cause. The
    // ignore comments tell webpack and Turbopack to leave this import alone so the browser
    // fetches the module itself, which is how Pyodide expects to be loaded.
    const { loadPyodide } = (await import(
      /* webpackIgnore: true */ /* turbopackIgnore: true */
      RUNTIME_MODULE
    )) as { loadPyodide: typeof import("pyodide").loadPyodide };

    const pyodide = await loadPyodide({
      // The interpreter itself is served from this origin, copied out of `node_modules` by
      // `npm run pyodide`. That pins it to the version in `package-lock.json` rather than
      // whatever a CDN is serving today, which for a WebAssembly build of CPython is worth
      // being deliberate about.
      indexURL: "/pyodide/",
      // Package wheels still come from Pyodide's own CDN. numpy, pandas, matplotlib and scipy
      // together are about sixty megabytes of vendor binary, which is not worth committing to
      // a repository to save a download that happens once per browser and is then cached.
      // Setting this explicitly matters: `packageBaseUrl` otherwise inherits `indexURL`, and
      // every package load would 404 against a directory holding only the core.
      packageBaseUrl: `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`,
    });

    onProgress?.("Loading numpy, pandas, matplotlib, scipy…");
    await pyodide.loadPackage([...PRELOAD]);

    // Agg because there is no display to draw into. Without it, importing pyplot fails with a
    // backend error that says nothing about the real cause.
    await pyodide.runPythonAsync("import matplotlib; matplotlib.use('Agg')");
    await pyodide.runPythonAsync(HARNESS);

    runtime = pyodide;
    onProgress?.("Ready");
    return pyodide;
  })();

  loading.catch(() => {
    // Cleared so a failed load can be retried rather than returning the same rejection for
    // the rest of the session.
    loading = null;
  });

  return loading;
}

/** Whether the interpreter is already in memory, so the UI can say "Run" rather than "Load". */
export function isRuntimeReady(): boolean {
  return runtime !== null;
}

/**
 * Run one cell.
 *
 * Cells share a namespace and run in the order you run them, which is what makes a notebook a
 * notebook: `df` defined in cell one is there in cell three. It is also the thing that makes
 * notebooks confusing, which is why an edited cell is marked stale server-side.
 */
export async function runCell(
  source: string,
  onProgress?: (message: string) => void,
): Promise<RunResult> {
  const started = performance.now();
  const pyodide = await loadRuntime(onProgress);

  const namespace = pyodide.globals.get("__turex_namespace") ?? pyodide.toPy({});
  pyodide.globals.set("__turex_namespace", namespace);

  // Imports a cell asks for are fetched before it runs, so `import pandas` works without the
  // reader having to know that a package has to be installed first.
  try {
    await pyodide.loadPackagesFromImports(source);
  } catch {
    // A package Pyodide does not carry is not a reason to refuse the cell — the import will
    // raise inside Python, where the traceback names it, which is a better error than this
    // one could be.
  }

  const runner = pyodide.globals.get("__turex_run");
  const result = runner(source, namespace);

  try {
    const plain = result.toJs({ dict_converter: Object.fromEntries }) as {
      output: string;
      image: string | null;
      error: string | null;
    };

    return {
      output: plain.output ?? "",
      image: plain.image ?? null,
      error: plain.error ?? null,
      durationMs: Math.round(performance.now() - started),
    };
  } finally {
    // Proxies to Python objects are not garbage collected by the JS engine — it cannot see
    // into the WASM heap — so they leak until destroyed. One per cell run adds up over a
    // session of iterating on the same cell.
    result.destroy?.();
    runner.destroy?.();
  }
}

/**
 * Forget every variable, keeping the interpreter loaded.
 *
 * The notebook equivalent of restarting the kernel, and the answer to "why does this work
 * only when I run the cells in this order". Keeping the interpreter avoids re-downloading
 * 13MB to answer a question about state.
 */
export function resetNamespace(): void {
  if (!runtime) return;
  const existing = runtime.globals.get("__turex_namespace");
  existing?.destroy?.();
  runtime.globals.set("__turex_namespace", runtime.toPy({}));
}
