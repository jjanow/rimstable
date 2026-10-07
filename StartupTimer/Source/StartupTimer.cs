using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using HarmonyLib;
using Verse;

namespace RimstableStartupTimer
{
    // Times startup per mod: mod constructors, [StaticConstructorOnStartup] classes, ExecuteWhenFinished
    // callbacks, Harmony patching inside each of those, plus the game's own DeepProfiler stages.
    // Load it right after Harmony so its constructor runs before (almost) every other mod class.
    // Writes <userdata>/StartupTimer.txt once the game reaches the main menu, then goes idle.
    public class StartupTimerMod : Mod
    {
        public StartupTimerMod(ModContentPack content) : base(content)
        {
            Timer.Init(content);
        }
    }

    class Frame
    {
        public string kind, label, mod;
        public int thread, depth;
        public double start, ms, harmonyMs;
        public int patches;
        public long t0;
        public bool attributedAncestor;
    }

    static class Timer
    {
        const string Game = "[game] Assembly-CSharp";
        static readonly DateTime procStart = Process.GetCurrentProcess().StartTime;
        static readonly long swStart = Stopwatch.GetTimestamp();
        static readonly double swOffset = (DateTime.Now - procStart).TotalSeconds;
        static double Now => swOffset + Secs(Stopwatch.GetTimestamp() - swStart);
        static double Secs(long ticks) => ticks / (double)Stopwatch.Frequency;

        static readonly object lk = new object();
        static readonly List<Frame> frames = new List<Frame>();
        static readonly Dictionary<Assembly, string> asmToMod = new Dictionary<Assembly, string>();
        static readonly Dictionary<string, string> modClassToMod = new Dictionary<string, string>();
        static readonly Dictionary<string, string> packageToMod = new Dictionary<string, string>();
        [ThreadStatic] static Stack<Frame> stack;
        static volatile bool done;
        static double initAt, initMs, harmonyTotalMs, harmonyOutsideMs;
        static int harmonyTotal;
        static Assembly self;
        static readonly List<string> notes = new List<string>();

        public static void Init(ModContentPack content)
        {
            initAt = Now;
            self = typeof(Timer).Assembly;
            foreach (var mcp in LoadedModManager.RunningModsListForReading)
            {
                packageToMod[mcp.ToString()] = mcp.Name;
                foreach (var a in mcp.assemblies.loadedAssemblies)
                    asmToMod[a] = mcp.Name;
            }
            foreach (var t in typeof(Mod).InstantiableDescendantsAndSelf())
                modClassToMod[t.ToString()] = ModOf(t.Assembly);

            var created = (Dictionary<Type, Mod>)AccessTools.Field(typeof(LoadedModManager), "runningModClasses").GetValue(null);
            var before = created.Keys.Where(t => t.Assembly != self).Select(t => ModOf(t.Assembly)).Distinct().ToList();
            if (before.Count > 0)
                notes.Add("Mod classes created before the timer (not timed): " + string.Join(", ", before));

            var h = new Harmony("rimstable.startuptimer");
            Patch(h, AccessTools.Method(typeof(DeepProfiler), nameof(DeepProfiler.Start)), prefix: nameof(DpStart));
            Patch(h, AccessTools.Method(typeof(DeepProfiler), nameof(DeepProfiler.End)), prefix: nameof(DpEnd));
            Patch(h, AccessTools.Method(typeof(StaticConstructorOnStartupUtility), nameof(StaticConstructorOnStartupUtility.CallAll)), prefix: nameof(CallAllPrefix));
            Patch(h, AccessTools.Method(typeof(LongEventHandler), nameof(LongEventHandler.ExecuteWhenFinished)), prefix: nameof(EwfPrefix));
            Patch(h, AccessTools.Method(typeof(LongEventHandler), "ExecuteToExecuteWhenFinished"), postfix: nameof(EwfRunPostfix));
            Patch(h, AccessTools.Method("HarmonyLib.PatchFunctions:UpdateWrapper"), prefix: nameof(HarmonyPrefix), postfix: nameof(HarmonyPostfix));
            initMs = (Now - initAt) * 1000;
        }

        static void Patch(Harmony h, MethodBase target, string prefix = null, string postfix = null)
        {
            if (target == null)
            {
                notes.Add($"Target for {prefix ?? postfix} not found; that part is not measured");
                return;
            }
            try
            {
                h.Patch(target,
                    prefix: prefix == null ? null : new HarmonyMethod(typeof(Timer), prefix),
                    postfix: postfix == null ? null : new HarmonyMethod(typeof(Timer), postfix));
            }
            catch (Exception e)
            {
                notes.Add($"Could not patch {target.DeclaringType}.{target.Name}: {e.Message}");
            }
        }

        static string ModOf(Assembly a)
        {
            if (a == null)
                return null;
            if (asmToMod.TryGetValue(a, out var m))
                return m;
            return a.GetName().Name == "Assembly-CSharp" ? Game : "[asm] " + a.GetName().Name;
        }

        static Frame Push(string kind, string label, string mod)
        {
            stack ??= new Stack<Frame>();
            var f = new Frame
            {
                kind = kind, label = label, mod = mod, thread = Environment.CurrentManagedThreadId,
                depth = stack.Count, start = Now, t0 = Stopwatch.GetTimestamp(),
                attributedAncestor = stack.Any(p => p.mod != null),
            };
            stack.Push(f);
            return f;
        }

        static void Pop()
        {
            if (stack == null || stack.Count == 0)
                return; // End() for a Start() that began before we patched
            var f = stack.Pop();
            f.ms = Secs(Stopwatch.GetTimestamp() - f.t0) * 1000;
            if (stack.Count > 0)
            {
                var p = stack.Peek();
                p.harmonyMs += f.harmonyMs;
                p.patches += f.patches;
            }
            lock (lk)
                frames.Add(f);
        }

        static void DpStart(string label)
        {
            if (done)
                return;
            string mod = null, kind = "stage";
            if (label != null && label.StartsWith("Loading "))
            {
                if (label.EndsWith(" mod class"))
                {
                    modClassToMod.TryGetValue(label.Substring(8, label.Length - 18), out mod);
                    kind = "mod class";
                }
                else if (packageToMod.TryGetValue(label.Substring(8), out mod))
                    kind = "xml";
            }
            Push(kind, label ?? "(null)", mod);
        }

        static void DpEnd()
        {
            if (!done)
                Pop();
        }

        // Runs the constructors one at a time with timing, in the original order. The original CallAll then
        // finds them already run (and re-throws/logs any that failed, exactly as before).
        static void CallAllPrefix()
        {
            if (done)
                return;
            foreach (var t in GenTypes.AllTypesWithAttribute<StaticConstructorOnStartup>())
            {
                Push("static ctor", t.ToString(), ModOf(t.Assembly));
                try { RuntimeHelpers.RunClassConstructor(t.TypeHandle); }
                catch { }
                finally { Pop(); }
            }
        }

        static void EwfPrefix(ref Action action)
        {
            if (done || action == null)
                return;
            var m = action.Method;
            var asm = m.DeclaringType?.Assembly;
            var mod = ModOf(asm);
            if (asm == self || mod == null || mod == Game)
                return;
            var inner = action;
            var label = m.DeclaringType + " -> " + m.Name;
            action = () =>
            {
                Push("delayed init", label, mod);
                try { inner(); }
                finally { Pop(); }
            };
        }

        static void HarmonyPrefix(out long __state) => __state = Stopwatch.GetTimestamp();

        static void HarmonyPostfix(long __state)
        {
            if (done)
                return;
            double ms = Secs(Stopwatch.GetTimestamp() - __state) * 1000;
            lock (lk)
            {
                harmonyTotalMs += ms;
                harmonyTotal++;
            }
            if (stack != null && stack.Count > 0)
            {
                var f = stack.Peek();
                f.harmonyMs += ms;
                f.patches++;
            }
            else
                lock (lk)
                    harmonyOutsideMs += ms;
        }

        static void EwfRunPostfix()
        {
            if (done || !PlayDataLoader.Loaded)
                return;
            done = true;
            try { Report(); }
            catch (Exception e) { Log.Error("[StartupTimer] report failed: " + e); }
        }

        static void Report()
        {
            double end = Now;
            List<Frame> all;
            lock (lk)
                all = frames.ToList();
            var sb = new StringBuilder();
            sb.AppendLine($"RimWorld startup timing — {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            sb.AppendLine($"Main menu reached {end:F1}s after process start. Timer started at {initAt:F1}s (setup {initMs:F0} ms).");
            sb.AppendLine($"Harmony: {harmonyTotal} method patches applied after the timer started, {harmonyTotalMs / 1000:F1}s in total " +
                          $"({harmonyOutsideMs / 1000:F1}s outside any timed step).");
            foreach (var n in notes)
                sb.AppendLine("Note: " + n);
            sb.AppendLine("Times include everything a step triggers (JIT compiling, nested loads); Harmony = time spent applying patches inside it.");

            sb.AppendLine().AppendLine("== Stages (top-level steps; anything over 0.3s) ==");
            sb.AppendLine("   start   secs  harmony  thread  step");
            foreach (var f in all.Where(f => f.depth == 0 && f.ms >= 300).OrderBy(f => f.start))
                sb.AppendLine($"{f.start,7:F1}s {f.ms / 1000,6:F1} {f.harmonyMs / 1000,7:F1}s {f.thread,6}  {f.label}");
            var gaps = all.Where(f => f.depth == 0).Sum(f => f.ms) / 1000;
            sb.AppendLine($"Sum of all top-level steps: {gaps:F1}s of the {end - initAt:F1}s since the timer started.");

            var owned = all.Where(f => f.mod != null && !f.attributedAncestor).ToList();
            sb.AppendLine().AppendLine("== Per mod (mod class + static ctors + delayed init + XML load) ==");
            sb.AppendLine("  total   class  static  delayed   xml   harmony patches  mod");
            var byMod = owned.GroupBy(f => f.mod)
                .Select(g => new
                {
                    mod = g.Key,
                    total = g.Sum(f => f.ms),
                    cls = g.Where(f => f.kind == "mod class").Sum(f => f.ms),
                    st = g.Where(f => f.kind == "static ctor").Sum(f => f.ms),
                    del = g.Where(f => f.kind == "delayed init").Sum(f => f.ms),
                    xml = g.Where(f => f.kind == "xml").Sum(f => f.ms),
                    harm = g.Sum(f => f.harmonyMs),
                    patches = g.Sum(f => f.patches),
                })
                .OrderByDescending(x => x.total).ToList();
            foreach (var x in byMod)
                sb.AppendLine($"{x.total / 1000,6:F2}s {x.cls / 1000,6:F2} {x.st / 1000,6:F2} {x.del / 1000,7:F2} {x.xml / 1000,6:F2} {x.harm / 1000,7:F2}s {x.patches,6}  {x.mod}");
            sb.AppendLine($"Sum over all mods: {byMod.Sum(x => x.total) / 1000:F1}s, of which Harmony patching {byMod.Sum(x => x.harm) / 1000:F1}s.");

            sb.AppendLine().AppendLine("== Slowest single steps owned by a mod (top 60) ==");
            foreach (var f in owned.OrderByDescending(f => f.ms).Take(60))
                sb.AppendLine($"{f.ms / 1000,6:F2}s  harmony {f.harmonyMs / 1000,5:F2}s  {f.kind,-12} {f.mod}: {f.label}");

            sb.AppendLine().AppendLine("== Slowest game steps not owned by a mod (top 40) ==");
            foreach (var f in all.Where(f => f.mod == null && f.depth > 0).OrderByDescending(f => f.ms).Take(40))
                sb.AppendLine($"{f.ms / 1000,6:F2}s  depth {f.depth}  {f.label}");

            sb.AppendLine().AppendLine("== Harmony patches currently applied, by owner ==");
            var owners = new Dictionary<string, int>();
            foreach (var m in Harmony.GetAllPatchedMethods().ToList())
                foreach (var o in Harmony.GetPatchInfo(m)?.Owners ?? Enumerable.Empty<string>())
                    owners[o] = owners.TryGetValue(o, out var c) ? c + 1 : 1;
            foreach (var kv in owners.OrderByDescending(kv => kv.Value))
                sb.AppendLine($"{kv.Value,6}  {kv.Key}");

            var path = Path.Combine(GenFilePaths.SaveDataFolderPath, "StartupTimer.txt");
            File.WriteAllText(path, sb.ToString());
            Log.Message($"[StartupTimer] main menu at {end:F1}s; report written to {path}");
        }
    }
}
