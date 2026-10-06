using System.Linq;
using HarmonyLib;
using Verse;
using Verse.Steam;

namespace RimstableNoSteamNag
{
    public class NoSteamNagMod : Mod
    {
        public NoSteamNagMod(ModContentPack content) : base(content)
        {
            new Harmony("rimstable.nosteamnag").PatchAll();
        }
    }

    // UIRoot_Entry.Init adds the "SteamClientMissing" dialog whenever Steam is not initialized.
    [HarmonyPatch(typeof(UIRoot_Entry), nameof(UIRoot_Entry.Init))]
    static class UIRoot_Entry_Init_Patch
    {
        static void Postfix()
        {
            if (SteamManager.Initialized)
                return;
            string nag = "SteamClientMissing".Translate();
            foreach (var box in Find.WindowStack.Windows.OfType<Dialog_MessageBox>().Where(b => b.text == nag).ToList())
                Find.WindowStack.TryRemove(box, doCloseSound: false);
        }
    }
}
