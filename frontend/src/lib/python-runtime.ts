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
 * The core interpreter is warmed on opening the workstation and reused within the tab.
 * Science packages load only when a cell imports them.
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
let progressMessage = "Downloading Python…";
const progressListeners = new Set<(message: string) => void>();

function reportProgress(message: string) {
  progressMessage = message;
  for (const listener of progressListeners) listener(message);
}

async function withTimeout<T>(promise: Promise<T>, milliseconds: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(message)), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export async function loadRuntime(onProgress?: (message: string) => void): Promise<PyodideInterface> {
  if (runtime) return runtime;
  if (onProgress) {
    progressListeners.add(onProgress);
    onProgress(progressMessage);
  }

  if (!loading) {
    const initialise = async () => {
      reportProgress("Downloading Python…");
      const { loadPyodide } = (await import(
        /* webpackIgnore: true */ /* turbopackIgnore: true */
        RUNTIME_MODULE
      )) as { loadPyodide: typeof import("pyodide").loadPyodide };
      reportProgress("Starting Python…");
      const pyodide = await loadPyodide({
        indexURL: "/pyodide/",
        packageBaseUrl: new URL("/pyodide/", window.location.href).href,
      });
      // Configure plotting without importing matplotlib until a cell actually needs it.
      await pyodide.runPythonAsync("import os; os.environ['MPLBACKEND'] = 'Agg'");
      await pyodide.runPythonAsync(HARNESS);
      return pyodide;
    };
    loading = withTimeout(initialise(), 45_000,
      "Python took too long to start. Check your connection and press Run to retry.")
      .then((pyodide) => {
        runtime = pyodide;
        reportProgress("Ready");
        return pyodide;
      }).catch((error) => {
        loading = null;
        throw error;
      });
  }
  try {
    return await loading;
  } finally {
    if (onProgress) progressListeners.delete(onProgress);
  }
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

  // Only fetch the packages this cell imports; basic Python needs no science downloads.
  const packageErrors: string[] = [];
  await withTimeout(pyodide.loadPackagesFromImports(source, {
    messageCallback: (message) => onProgress?.(message),
    errorCallback: (message) => packageErrors.push(message),
  }), 60_000, "Python packages took too long to load. Check your connection and press Run to retry.");
  if (packageErrors.length) {
    throw new Error(`Couldn't load Python packages. ${packageErrors.join(" ")} Press Run to retry.`);
  }
  onProgress?.("Running…");
  const namespace = pyodide.globals.get("__turex_namespace") ?? pyodide.toPy({});
  pyodide.globals.set("__turex_namespace", namespace);

  const runner = pyodide.globals.get("__turex_run");

  try {
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
      result.destroy?.();
    }
  } finally {
    // Proxies to Python objects are not garbage collected by the JS engine — it cannot see
    // into the WASM heap — so they leak until destroyed. One per cell run adds up over a
    // session of iterating on the same cell.
    runner.destroy?.();
    namespace.destroy?.();
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
  const empty = runtime.toPy({});
  try {
    runtime.globals.set("__turex_namespace", empty);
  } finally {
    empty.destroy?.();
  }
}
