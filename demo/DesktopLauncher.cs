using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class DesktopLauncher
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string path);

    [DllImport("python314.dll", CallingConvention = CallingConvention.Cdecl)]
    private static extern int Py_Main(int argc,
        [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.LPWStr)] string[] argv);

    [STAThread]
    private static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string runtime = Path.Combine(root, @"runtime\python");
        string script = Path.Combine(root, @"source\demo\desktop.py");
        try
        {
            if (!File.Exists(script) || !File.Exists(Path.Combine(runtime, "python314.dll")))
                throw new FileNotFoundException("请完整解压便携包，再打开桌面客户端。");
            if (!SetDllDirectory(runtime))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());

            // 直接运行随包 Python，让桌面窗口与 EXE 共用一个进程。
            string[] arguments = { Path.Combine(runtime, "pythonw.exe"), "-X", "utf8", script };
            return Py_Main(arguments.Length, arguments);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Skill Inventory 客户端",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
