// iphonecall: dial and answer phone calls from the terminal through Windows' own hands-free
// calling (the PhoneLine APIs Phone Link uses), with the call voice on the laptop.
// Setup, usage and development notes: ..\README.md
using System.Runtime.InteropServices;
using Windows.ApplicationModel.Activation;
using Windows.ApplicationModel.Calls;

const string Usage = "usage: iphonecall [shell | dial <number> | status | list | list-json | lines | phones | self-test | audio-devices-json | unregister | pair [--json]] [--device <name> | --device-id <id>] [--stay-on-phone] [--follow-phone]";
const string Help = "commands: d <number> dial | a answer | h hang up/reject | m mute on/off |\n" +
                    "          l audio on laptop | p audio on phone | s status | q quit";

// Windows opens this for every call and agents drive it over pipes, and neither wants a terminal. Only a person running it does.
if (!Terminal.HasPipes())
{
    bool openedByWindows;
    try { openedByWindows = Windows.ApplicationModel.AppInstance.GetActivatedEventArgs() is PhoneCallActivatedEventArgs; }
    catch (Exception) { openedByWindows = false; }
    if (!openedByWindows) Terminal.Open();
}

string? deviceHint = null;
string? deviceId = null;
bool stayOnPhone = false;
bool followPhone = false;
var rest = new List<string>();
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "--device" && i + 1 < args.Length) deviceHint = args[++i];
    else if (args[i] == "--device-id" && i + 1 < args.Length) deviceId = args[++i];
    else if (args[i] == "--stay-on-phone") stayOnPhone = true;
    else if (args[i] == "--follow-phone") followPhone = true;
    else rest.Add(args[i]);
}
string action = rest.Count > 0 ? rest[0].ToLowerInvariant() : "shell";
if (action is not ("shell" or "dial" or "status" or "list" or "list-json" or "lines" or "phones" or "self-test" or "audio-devices-json" or "unregister" or "pair"))
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
    if (action == "list-json")
    {
        await HandsFree.ListJsonAsync();
        return 0;
    }
    if (action == "lines")
    {
        await HandsFree.LinesAsync();
        return 0;
    }
    if (action == "self-test") return PhoneSelection.SelfTest() == 0 ? 0 : 1;
    if (action == "pair") return await Pairing.RunAsync(rest.Skip(1).Contains("--json"));

    var info = await HandsFree.FindAsync(deviceHint, deviceId);
    if (info == null && !string.IsNullOrEmpty(deviceId))
    {
        // A phone chosen in Pat's settings that has since been unpaired, such as one that was sold: use whichever phone is here.
        Console.WriteLine("phone    : the phone chosen in Pat's settings isn't paired any more; choosing automatically");
        deviceId = null;
        info = await HandsFree.FindAsync(deviceHint, null);
    }
    if (action == "phones")
    {
        await HandsFree.PhonesAsync(info);
        return 0;
    }
    if (action == "audio-devices-json")
    {
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(await BluetoothAudio.InventoryAsync(info)));
        return 0;
    }
    if (info == null)
    {
        await Pairing.SayNotificationsOnlyAsync();
        Console.WriteLine("No paired hands-free phone matches the selection. Pair your phone or choose it in Pat's settings. Try: iphonecall list");
        return 1;
    }
    if (action == "unregister")
    {
        HandsFree.Unregister(info);
        Console.WriteLine($"unregistered from {info.Name}");
        return 0;
    }

    var (line, phone) = await HandsFree.ConnectAnyAsync(info);
    if (line == null || phone == null)
    {
        await Pairing.SayNotificationsOnlyAsync();
        return 1;
    }

    // --follow-phone: for a shell that waits for calls for hours. It closes, so its owner can start a new one, when the
    // phone in use disconnects, or when a phone chosen by --device-id comes back after this line fell back to another.
    var watch = followPhone ? await PhoneWatch.CreateAsync(phone, string.IsNullOrEmpty(deviceId) ? null : info) : null;
    var session = new CallSession(line) { CloseAfterCalls = openedForCall, MoveToLaptop = !(openedForCall || stayOnPhone), Watch = watch };
    if (openedForCall) Console.WriteLine("opened by Windows for a call; this window closes when the call ends");
    session.PrintStatus();
    if (action == "status") return 0;
    if (action == "dial") session.Dial(rest[1]);
    await RunShellAsync(session);
    return 0;
}
catch (InvalidOperationException e)
{
    await Pairing.SayNotificationsOnlyAsync();
    Console.WriteLine($"error: {e.Message}");
    return 1;
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
    if (session.CloseAfterCalls)
    {
        await monitor; // nobody to type here; it exits by itself once the call is over
        return;
    }
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

static class Terminal
{
    [DllImport("kernel32.dll")] private static extern IntPtr GetStdHandle(int which);
    [DllImport("kernel32.dll")] private static extern bool AllocConsole();
    [DllImport("kernel32.dll")] private static extern bool GetConsoleMode(IntPtr handle, out uint mode);
    [DllImport("kernel32.dll")] private static extern bool SetConsoleMode(IntPtr handle, uint mode);
    private const int StdOutput = -11;
    private const int StdInput = -10;
    private const uint QuickEdit = 0x40, ExtendedFlags = 0x80;

    public static bool HasPipes()
    {
        IntPtr output = GetStdHandle(StdOutput);
        return output != IntPtr.Zero && output != new IntPtr(-1);
    }

    // Without Quick Edit, a click in the window can't pause it: a paused window shows nothing new until a key is pressed.
    public static void Open()
    {
        AllocConsole();
        IntPtr input = GetStdHandle(StdInput);
        if (GetConsoleMode(input, out uint mode)) SetConsoleMode(input, (mode | ExtendedFlags) & ~QuickEdit);
    }
}
