using System;
using System.Linq;
using SharpShell.ServerRegistration;
using SharpShell.SharpThumbnailHandler;
using YtdThumbnail;

namespace RegisterShell;

internal static class Program
{
    private const RegistrationType RegType = RegistrationType.OS64Bit;

    private static int Main(string[] args)
    {
        var cmd = args.Length > 0 ? args[0].ToLowerInvariant() : "install";
        var handlers = new SharpThumbnailHandler[] { new YtdSharpHandler(), new YddSharpHandler() };

        try
        {
            if (cmd == "uninstall")
            {
                foreach (var server in handlers)
                {
                    ServerRegistrationManager.UninstallServer(server, RegType);
                    ServerRegistrationManager.UnregisterServer(server, RegType);
                    Console.WriteLine("SharpShell: unregistered " + server.GetType().Name);
                }
            }
            else
            {
                foreach (var server in handlers)
                {
                    ServerRegistrationManager.UninstallServer(server, RegType);
                    ServerRegistrationManager.InstallServer(server, RegType, codeBase: true);
                    ServerRegistrationManager.RegisterServer(server, RegType);
                    Console.WriteLine("SharpShell: registered " + server.GetType().Name + " (" + server.ServerClsid + ")");
                }
            }

            if (cmd == "uninstall")
                Console.WriteLine("SharpShell: all handlers removed.");
            else
                Console.WriteLine("SharpShell: done (64-bit, codebase).");

            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR: " + ex.Message);
            return 3;
        }
    }
}
