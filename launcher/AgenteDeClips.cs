// Lanzador del Agente de Clips.
// Doble clic: instala/actualiza dependencias si hace falta, levanta el servidor
// (backend FastAPI + interfaz web), abre el navegador y queda en la bandeja del sistema.
// Compilar con launcher\build.ps1 (usa el csc.exe incluido en Windows).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Management;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        bool first;
        using (var mutex = new Mutex(true, "Local\\AgenteDeClips.Launcher", out first))
        {
            if (!first)
            {
                // Ya hay un lanzador en la bandeja: solo abrir la interfaz.
                Launcher.OpenBrowser();
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new Launcher(args));
            GC.KeepAlive(mutex);
        }
    }
}

class Launcher : ApplicationContext
{
    const string Url = "http://localhost:8585";
    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    const string AppName = "Agente de Clips";

    readonly string root;
    readonly string venvPy;
    readonly string logPath;
    readonly bool minimized;
    readonly NotifyIcon tray;
    readonly Control ui;
    readonly ToolStripMenuItem miRestart, miStartup;
    readonly object logLock = new object();

    Process server;
    StreamWriter log;
    volatile bool stopping;

    public Launcher(string[] args)
    {
        root = Path.GetDirectoryName(Application.ExecutablePath);
        venvPy = Path.Combine(root, @"venv\Scripts\python.exe");
        logPath = Path.Combine(root, @"data\server.log");
        minimized = Array.IndexOf(args, "--minimized") >= 0;

        ui = new Control();
        ui.CreateControl();

        var menu = new ContextMenuStrip();
        var miOpen = new ToolStripMenuItem("Abrir interfaz", null, delegate { OpenBrowser(); });
        miOpen.Font = new Font(miOpen.Font, FontStyle.Bold);
        menu.Items.Add(miOpen);
        menu.Items.Add("Ver registro del servidor", null, delegate { OpenLog(); });
        menu.Items.Add("Abrir carpeta del proyecto", null, delegate { Shell(root); });
        menu.Items.Add(new ToolStripSeparator());
        miRestart = new ToolStripMenuItem("Reiniciar servidor", null, delegate { Restart(); });
        menu.Items.Add(miRestart);
        miStartup = new ToolStripMenuItem("Iniciar con Windows", null, delegate { ToggleStartup(); });
        miStartup.Checked = StartupEnabled();
        menu.Items.Add(miStartup);
        menu.Items.Add("Crear acceso directo en el escritorio", null, delegate { CreateShortcut(); });
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Detener y salir", null, delegate { Quit(); });

        tray = new NotifyIcon();
        try { tray.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
        catch { tray.Icon = SystemIcons.Application; }
        tray.Text = AppName + " — iniciando…";
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += delegate { OpenBrowser(); };
        tray.BalloonTipClicked += delegate { if (server != null && !server.HasExited) OpenBrowser(); else Restart(); };
        tray.Visible = true;

        new Thread(Boot) { IsBackground = true }.Start();
    }

    // ── arranque ─────────────────────────────────────────
    void Boot()
    {
        try
        {
            if (ServerAlive())
            {
                // Ya lo levantó otro proceso (p. ej. run_ui.ps1): no hay nada que administrar.
                OpenBrowser();
                Ui(delegate { tray.Visible = false; ExitThread(); });
                return;
            }
            if (!EnsureInstalled()) { Ui(delegate { tray.Visible = false; ExitThread(); }); return; }
            StartServer(!minimized);
        }
        catch (Exception ex)
        {
            Ui(delegate
            {
                MessageBox.Show("No se pudo iniciar: " + ex.Message, AppName, MessageBoxButtons.OK, MessageBoxIcon.Error);
                tray.Visible = false;
                ExitThread();
            });
        }
    }

    bool EnsureInstalled()
    {
        string reqFile = Path.Combine(root, "requirements.txt");
        string marker = Path.Combine(root, @"venv\.requirements.sha256");
        string lockFile = Path.Combine(root, @"motion\package-lock.json");
        string want = Sha256(reqFile) + "-" + Sha256(lockFile);
        string have = File.Exists(marker) ? File.ReadAllText(marker).Trim() : "";
        // Node.js instalado después: falta instalar Remotion para las animaciones
        bool motionMissing = File.Exists(lockFile) && OnPath("node.exe")
                             && !Directory.Exists(Path.Combine(root, @"motion\node_modules\remotion"));
        if (File.Exists(venvPy) && !motionMissing && string.Equals(want, have, StringComparison.OrdinalIgnoreCase))
            return true;

        bool firstTime = !File.Exists(venvPy);
        SetStatus(firstTime ? "instalando…" : "actualizando dependencias…");
        Balloon(firstTime ? "Primera ejecución: instalando dependencias (puede tardar unos minutos)."
                          : "Actualizando dependencias…", ToolTipIcon.Info);

        var psi = new ProcessStartInfo("powershell.exe",
            "-NoProfile -ExecutionPolicy Bypass -Command \"& '.\\setup.ps1'; $c = $LASTEXITCODE; " +
            "if ($c) { Read-Host 'La instalacion fallo. Presiona Enter para cerrar' }; exit $c\"");
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        using (var p = Process.Start(psi))
        {
            p.WaitForExit();
            if (p.ExitCode == 0 && File.Exists(venvPy)) return true;
        }
        Ui(delegate
        {
            MessageBox.Show("La instalación no terminó correctamente.\n\nRevisa que Python 3.11+ esté instalado " +
                            "(con «Add python.exe to PATH») y que tengas conexión a internet, y vuelve a abrir el programa.",
                            AppName, MessageBoxButtons.OK, MessageBoxIcon.Error);
        });
        return false;
    }

    void StartServer(bool openBrowser)
    {
        stopping = false;
        SetStatus("iniciando…");
        Ui(delegate { miRestart.Enabled = false; });
        Directory.CreateDirectory(Path.GetDirectoryName(logPath));
        lock (logLock)
        {
            if (log != null) log.Dispose();
            log = new StreamWriter(logPath, false, new UTF8Encoding(false));
            log.AutoFlush = true;
            log.WriteLine("=== " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " servidor iniciado ===");
        }

        var psi = new ProcessStartInfo(venvPy, "-m app.server --no-browser");
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";

        var p = new Process();
        p.StartInfo = psi;
        p.EnableRaisingEvents = true;
        p.OutputDataReceived += OnOutput;
        p.ErrorDataReceived += OnOutput;
        p.Exited += OnServerExited;
        p.Start();
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        server = p;

        var sw = Stopwatch.StartNew();
        while (sw.Elapsed.TotalSeconds < 90)
        {
            if (p.HasExited) return;  // OnServerExited avisa
            if (ServerAlive())
            {
                SetStatus("en ejecución");
                LogLine("=== servidor listo en " + sw.Elapsed.TotalSeconds.ToString("0.0") + " s ===");
                Ui(delegate { miRestart.Enabled = true; });
                if (openBrowser) OpenBrowser();
                else Balloon("Servidor en ejecución. Doble clic en el icono para abrir la interfaz.", ToolTipIcon.Info);
                return;
            }
            Thread.Sleep(400);
        }
        SetStatus("no responde");
        Ui(delegate { miRestart.Enabled = true; });
        Balloon("El servidor no respondió a tiempo. Revisa el registro (clic derecho en el icono).", ToolTipIcon.Warning);
    }

    void OnOutput(object sender, DataReceivedEventArgs e)
    {
        if (e.Data == null) return;
        lock (logLock) { if (log != null) log.WriteLine(e.Data); }
    }

    void OnServerExited(object sender, EventArgs e)
    {
        if (stopping || sender != server) return;
        SetStatus("detenido");
        Ui(delegate { miRestart.Enabled = true; });
        Balloon("El servidor se detuvo inesperadamente. Haz clic aquí para reiniciarlo " +
                "o revisa el registro.", ToolTipIcon.Error);
    }

    // ── acciones del menú ────────────────────────────────
    void Restart()
    {
        if (!StopServer(true)) return;
        new Thread(delegate () { StartServer(false); }) { IsBackground = true }.Start();
    }

    void Quit()
    {
        if (!StopServer(false)) return;
        tray.Visible = false;
        lock (logLock) { if (log != null) { log.Dispose(); log = null; } }
        ExitThread();
    }

    /// Devuelve false si el usuario canceló.
    bool StopServer(bool restarting)
    {
        if (server == null || server.HasExited) return true;
        bool killTree = true;
        if (File.Exists(Path.Combine(root, @"runs\.active")))
        {
            var r = MessageBox.Show(
                "Hay un run en curso.\n\n" +
                "Sí: cancelarlo también.\n" +
                "No: dejarlo terminar en segundo plano (podrás verlo al volver a abrir la interfaz).",
                AppName + (restarting ? " — reiniciar" : " — salir"),
                MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
            if (r == DialogResult.Cancel) return false;
            killTree = r == DialogResult.Yes;
        }
        stopping = true;
        try
        {
            if (killTree)
            {
                Taskkill("/PID " + server.Id + " /T /F");
            }
            else
            {
                // venv\Scripts\python.exe es un lanzador que crea el intérprete real como hijo;
                // el run es nieto. Se detienen el lanzador y sus hijos directos, no el run.
                foreach (int pid in ChildPids(server.Id)) Taskkill("/PID " + pid + " /F");
                Taskkill("/PID " + server.Id + " /F");
            }
            server.WaitForExit(10000);
        }
        catch { }
        LogLine("=== servidor detenido ===");
        SetStatus("detenido");
        return true;
    }

    void OpenLog()
    {
        if (File.Exists(logPath)) Shell("notepad.exe", "\"" + logPath + "\"");
        else MessageBox.Show("Todavía no hay registro.", AppName);
    }

    bool StartupEnabled()
    {
        using (var k = Registry.CurrentUser.OpenSubKey(RunKey))
            return k != null && k.GetValue("AgenteDeClips") != null;
    }

    void ToggleStartup()
    {
        using (var k = Registry.CurrentUser.CreateSubKey(RunKey))
        {
            if (StartupEnabled()) k.DeleteValue("AgenteDeClips", false);
            else k.SetValue("AgenteDeClips", "\"" + Application.ExecutablePath + "\" --minimized");
        }
        miStartup.Checked = StartupEnabled();
    }

    void CreateShortcut()
    {
        try
        {
            string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                                       AppName + ".lnk");
            dynamic sh = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic lnk = sh.CreateShortcut(path);
            lnk.TargetPath = Application.ExecutablePath;
            lnk.WorkingDirectory = root;
            lnk.IconLocation = Application.ExecutablePath + ",0";
            lnk.Description = "Abre el Agente de Clips";
            lnk.Save();
            Balloon("Acceso directo creado en el escritorio.", ToolTipIcon.Info);
        }
        catch (Exception ex)
        {
            MessageBox.Show("No se pudo crear el acceso directo: " + ex.Message, AppName);
        }
    }

    // ── utilidades ───────────────────────────────────────
    public static void OpenBrowser() { Shell(Url); }

    static void Shell(string target, string args = null)
    {
        try { Process.Start(new ProcessStartInfo(target, args ?? "") { UseShellExecute = true }); }
        catch { }
    }

    static void Taskkill(string args)
    {
        var psi = new ProcessStartInfo("taskkill.exe", args);
        psi.CreateNoWindow = true;
        psi.UseShellExecute = false;
        using (var k = Process.Start(psi)) k.WaitForExit(10000);
    }

    static int[] ChildPids(int parent)
    {
        var list = new System.Collections.Generic.List<int>();
        using (var q = new ManagementObjectSearcher(
            "SELECT ProcessId FROM Win32_Process WHERE ParentProcessId=" + parent))
        using (var res = q.Get())
            foreach (ManagementObject mo in res) list.Add(Convert.ToInt32(mo["ProcessId"]));
        return list.ToArray();
    }

    void LogLine(string s)
    {
        lock (logLock) { if (log != null) log.WriteLine(s); }
    }

    static bool ServerAlive()
    {
        try
        {
            // 127.0.0.1 explícito: "localhost" puede resolver a ::1 y el servidor solo escucha en IPv4.
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8585/");
            req.Proxy = null;
            req.Timeout = 1500;
            using (var resp = (HttpWebResponse)req.GetResponse())
            using (var rd = new StreamReader(resp.GetResponseStream()))
                return resp.StatusCode == HttpStatusCode.OK && rd.ReadToEnd().Contains("api-token");
        }
        catch { return false; }
    }

    static bool OnPath(string exe)
    {
        foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
        {
            try { if (dir.Length > 0 && File.Exists(Path.Combine(dir.Trim(), exe))) return true; }
            catch { }
        }
        return false;
    }

    static string Sha256(string file)
    {
        if (!File.Exists(file)) return "";
        using (var sha = SHA256.Create())
        using (var fs = File.OpenRead(file))
            return BitConverter.ToString(sha.ComputeHash(fs)).Replace("-", "");
    }

    void SetStatus(string s)
    {
        Ui(delegate { tray.Text = AppName + " — " + s; });
    }

    void Balloon(string msg, ToolTipIcon icon)
    {
        Ui(delegate { tray.ShowBalloonTip(5000, AppName, msg, icon); });
    }

    void Ui(MethodInvoker a)
    {
        if (ui.InvokeRequired) ui.BeginInvoke(a); else a();
    }
}
