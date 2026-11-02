// iphonecall: dial and answer iPhone calls from the terminal through Windows' own hands-free
// calling (the PhoneLine APIs Phone Link uses), with the call voice on the laptop.
// Setup, usage and development notes: ..\README.md
using System.Runtime.InteropServices;
using Windows.ApplicationModel.Activation;
using Windows.ApplicationModel.Calls;

const string Usage = "usage: iphonecall [shell | dial <number> | status | list | unregister] [--device <name>]";
const string Help = "commands: d <number> dial | a answer | h hang up/reject | m mute on/off |\n" +
                    "          l audio on laptop | p audio on phone | s status | q quit";

string deviceHint = "iPhone";
var rest = new List<string>();
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "--device" && i + 1 < args.Length) deviceHint = args[++i];
    else rest.Add(args[i]);
}
string action = rest.Count > 0 ? rest[0].ToLowerInvariant() : "shell";
if (action is not ("shell" or "dial" or "status" or "list" or "unregister"))
{
    Console.WriteLine(Usage);
    return action is "help" or "-h" or "--help" ? 0 : 1;
}
if (action == "dial" && rest.Count < 2)
{
    Console.WriteLine("usage: iphonecall dial <number>");
    return 1;
}

// The manifest's windows.phoneCallActivation entry (needed for registration) also makes Windows
// start iphonecall by itself when a call begins. Such a launch becomes a call window that closes
// once the call is over, instead of a shell that stays open.
bool openedForCall;
try { openedForCall = Windows.ApplicationModel.AppInstance.GetActivatedEventArgs() is PhoneCallActivatedEventArgs; }
catch (Exception) { openedForCall = false; }

try
{
    if (action == "list")
    {
        await HandsFree.ListAsync();
        return 0;
    }

    var info = await HandsFree.FindAsync(deviceHint);
    if (info == null)
    {
        Console.WriteLine($"No paired hands-free phone matching \"{deviceHint}\". Try: iphonecall list");
        return 1;
    }
    if (action == "unregister")
    {
        HandsFree.Unregister(info);
        Console.WriteLine($"unregistered from {info.Name}");
        return 0;
    }

    var line = await HandsFree.ConnectAsync(info);
    if (line == null) return 1;

    var session = new CallSession(line) { CloseAfterCalls = openedForCall };
    if (openedForCall) Console.WriteLine("opened by Windows for a call; this window closes when the call ends");
    session.PrintStatus();
    if (action == "status") return 0;
    if (action == "dial") session.Dial(rest[1]);
    await RunShellAsync(session);
    return 0;
}
catch (TimeoutException e)
{
    Console.WriteLine($"\nstuck: {e.Message}");
    return 3;
}
catch (UnauthorizedAccessException)
{
    Console.WriteLine("Access denied by Windows. Run it as `iphonecall` (the installed package), not the .exe in pkg\\.");
    return 2;
}

static async Task RunShellAsync(CallSession session)
{
    using var cts = new CancellationTokenSource();
    var monitor = session.MonitorAsync(cts.Token);
    Console.WriteLine(Help);
    while (true)
    {
        Console.Write("call> ");
        string? input = Console.ReadLine()?.Trim();
        if (input == null || input == "q") break;
        if (input.Length == 0) continue;
        string word = input.Split(' ', 2)[0].ToLowerInvariant();
        string arg = input[word.Length..].Trim();
        try
        {
            switch (word)
            {
                case "d": session.Dial(arg); break;
                case "a": await session.AnswerAsync(); break;
                case "h": await session.HangUpAsync(); break;
                case "m": await session.ToggleMuteAsync(); break;
                case "l": await session.RouteAudioAsync(PhoneCallAudioDevice.LocalDevice); break;
                case "p": await session.RouteAudioAsync(PhoneCallAudioDevice.RemoteDevice); break;
                case "s": session.PrintStatus(); break;
                default: Console.WriteLine(Help); break;
            }
        }
        catch (Exception e) when (e is COMException or InvalidOperationException or ArgumentException)
        {
            Console.WriteLine($"error: {e.Message}");
        }
    }
    cts.Cancel();
    await monitor;
}
