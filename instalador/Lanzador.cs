// Instalador de Companion (el .exe de cada Release). Lleva dentro el programa en un .zip (recurso
// «paquete.zip», con su manifest.json y VERSION), lo descomprime en una carpeta temporal y abre la ventana de
// instalación de siempre (scripts\instalacion\ventana_instalar.ps1 -Paquete), que deja elegir la carpeta, copia solo lo que
// cambió y completa o actualiza lo demás. Al cerrarse la ventana se borra la carpeta temporal.
//
// Se compila con el csc.exe de .NET Framework que trae Windows (scripts\instalacion\crear_instalador.ps1).
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Instalar Companion")]
[assembly: AssemblyProduct("Companion")]
[assembly: AssemblyDescription("Instalador de Companion")]
[assembly: AssemblyCompany("Companion (github.com/dannymzyq/companion-ai)")]
[assembly: AssemblyCopyright("Companion")]
// La versión (AssemblyVersion, AssemblyFileVersion) la pone scripts\instalacion\crear_instalador.ps1 en Version.cs al compilar.

static class Lanzador
{
    [STAThread]
    static int Main()
    {
        string tmp = Path.Combine(Path.GetTempPath(), "CompanionSetup_" + Guid.NewGuid().ToString("N").Substring(0, 8));
        try
        {
            Directory.CreateDirectory(tmp);
            using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("paquete.zip"))
            {
                if (s == null) throw new InvalidOperationException("el instalador está incompleto (falta el paquete)");
                using (ZipArchive zip = new ZipArchive(s, ZipArchiveMode.Read))
                {
                    string rootFull = Path.GetFullPath(tmp);
                    if (!rootFull.EndsWith(Path.DirectorySeparatorChar.ToString()))
                        rootFull += Path.DirectorySeparatorChar;
                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        if (string.IsNullOrEmpty(entry.Name)) continue;
                        string dest = Path.GetFullPath(Path.Combine(rootFull, entry.FullName));
                        if (!dest.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("ruta fuera del paquete en " + entry.FullName);
                        string dir = Path.GetDirectoryName(dest);
                        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                        entry.ExtractToFile(dest, true);
                    }
                }
            }
            string ps = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                     @"WindowsPowerShell\v1.0\powershell.exe");
            string ventana = Path.Combine(tmp, @"scripts\instalacion\ventana_instalar.ps1");
            // Sin «-WindowStyle Hidden» (ya va sin consola con CreateNoWindow) y con RemoteSigned en vez de Bypass: los
            // scripts salen del propio .exe, sin la marca de «descargado de internet», así que RemoteSigned los deja
            // correr. Un .exe pequeño que abre PowerShell escondido con Bypass es justo lo que el antivirus asocia a un
            // virus (Windows marcó así la 0.8.6, 18 nov 2026).
            ProcessStartInfo psi = new ProcessStartInfo(ps,
                "-NoProfile -STA -ExecutionPolicy RemoteSigned -File \"" + ventana + "\" -Paquete \"" + tmp + "\"");
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WorkingDirectory = tmp;
            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode;
            }
        }
        catch (Exception e)
        {
            MessageBox.Show("No pude preparar la instalación: " + e.Message, "Companion",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally
        {
            try { Directory.Delete(tmp, true); } catch { }
        }
    }
}
