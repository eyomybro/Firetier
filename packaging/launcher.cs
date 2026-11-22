// Firetier.exe: one file that carries the whole portable build (Firetier-Windows.zip) as a resource.
// First run of a build unpacks it to %LOCALAPPDATA%\Firetier\app\<build hash>\, later runs start at once.
// Then it starts the bundled pythonw.exe with server.py ("Firetier.exe classic" starts firetier.py).
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Firetier")]
[assembly: AssemblyProduct("Firetier")]
[assembly: AssemblyDescription("Firetier FastFlag profile manager")]

static class Launcher
{
    const string Marker = ".complete";

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            string dir = Unpacked();
            bool classic = args.Length > 0 && string.Equals(args[0], "classic", StringComparison.OrdinalIgnoreCase);
            var cmd = new StringBuilder(Quote(Path.Combine(dir, classic ? "firetier.py" : "server.py")));
            for (int i = classic ? 1 : 0; i < args.Length; i++)
                cmd.Append(' ').Append(Quote(args[i]));
            var psi = new ProcessStartInfo(Path.Combine(dir, @"runtime\pythonw.exe"), cmd.ToString());
            psi.UseShellExecute = false;
            psi.WorkingDirectory = dir;
            psi.EnvironmentVariables["TCL_LIBRARY"] = Path.Combine(dir, @"runtime\tcl\tcl8.6");
            psi.EnvironmentVariables["TK_LIBRARY"] = Path.Combine(dir, @"runtime\tcl\tk8.6");
            // The updater replaces this file, so the server needs to know where it is.
            psi.EnvironmentVariables["FIRETIER_EXE"] = Assembly.GetExecutingAssembly().Location;
            psi.EnvironmentVariables.Remove("PYTHONHOME");
            psi.EnvironmentVariables.Remove("PYTHONPATH");
            Process.Start(psi).Dispose();
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("Firetier could not start.\n\n" + e.Message, "Firetier", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static string Unpacked()
    {
        var asm = Assembly.GetExecutingAssembly();
        string build;
        using (var r = new StreamReader(asm.GetManifestResourceStream("version.txt")))
            build = r.ReadToEnd().Trim();

        string home = Environment.GetEnvironmentVariable("FIRETIER_HOME");
        if (string.IsNullOrEmpty(home))
            home = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Firetier");
        string root = Path.Combine(home, "app");
        string dir = Path.Combine(root, build);
        if (File.Exists(Path.Combine(dir, Marker)))
            return dir;

        Directory.CreateDirectory(root);
        // A folder without the marker is a broken earlier unpack; clear it before trying again.
        if (Directory.Exists(dir))
            Directory.Delete(dir, true);

        // Unpack into a private folder, then move it into place in one step, so two launches at once
        // can't see a half-written build.
        string tmp = Path.Combine(root, ".unpack-" + Guid.NewGuid().ToString("N"));
        try
        {
            using (var zip = new ZipArchive(asm.GetManifestResourceStream("Firetier.zip"), ZipArchiveMode.Read))
                zip.ExtractToDirectory(tmp);
            File.WriteAllText(Path.Combine(tmp, Marker), build);
            try
            {
                Directory.Move(tmp, dir);
            }
            catch (IOException)
            {
                if (!File.Exists(Path.Combine(dir, Marker)))
                    throw;
            }
        }
        finally
        {
            if (Directory.Exists(tmp))
                TryDelete(tmp);
        }
        RemoveOldBuilds(root, build);
        return dir;
    }

    static void RemoveOldBuilds(string root, string keep)
    {
        foreach (string old in Directory.GetDirectories(root))
        {
            string name = Path.GetFileName(old);
            if (name == keep || name.StartsWith(".unpack-"))
                continue;
            // Renaming fails while an older Firetier still runs from that folder, so it is left alone.
            string gone = Path.Combine(root, ".old-" + Guid.NewGuid().ToString("N"));
            try { Directory.Move(old, gone); } catch (IOException) { continue; } catch (UnauthorizedAccessException) { continue; }
            TryDelete(gone);
        }
    }

    static void TryDelete(string path)
    {
        try { Directory.Delete(path, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    static string Quote(string s)
    {
        // CommandLineToArgvW rules: backslashes before a quote are doubled.
        var sb = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in s)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') sb.Append('\\', slashes * 2 + 1);
            else sb.Append('\\', slashes);
            slashes = 0;
            sb.Append(c);
        }
        sb.Append('\\', slashes * 2).Append('"');
        return sb.ToString();
    }
}
