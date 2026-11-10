using Windows.ApplicationModel.Calls;
using Windows.Devices.Enumeration;
using Windows.Foundation.Metadata;
using Windows.Media.Devices;

// iphonecall win10-probe: what Windows 10 offers for calls, where PhoneCall and GetAllActivePhoneCalls (build 20348+,
// so Windows 11 only on laptops) are missing. It changes nothing: it prints which calling APIs exist, every call state
// change Windows reports, and the call audio devices, and can dial with the old PhoneLine.Dial. Answering and hanging up
// are left to whatever Windows shows, which is what this is meant to find out.
static class Win10Probe
{
    const string Contract = "Windows.ApplicationModel.Calls.CallsPhoneContract";

    public static async Task<int> RunAsync(PhoneLine line)
    {
        Console.WriteLine($"windows  : build {Environment.OSVersion.Version.Build}");
        for (ushort v = 1; v <= 7; v++)
            Console.WriteLine($"contract : CallsPhoneContract v{v}.0 {(ApiInformation.IsApiContractPresent(Contract, v) ? "present" : "missing")}");
        Console.WriteLine($"api      : PhoneCall class {(ApiInformation.IsTypePresent("Windows.ApplicationModel.Calls.PhoneCall") ? "present" : "missing")}");
        foreach (var method in new[] { "Dial", "DialWithOptions", "DialWithResult", "GetAllActivePhoneCalls" })
            Console.WriteLine($"api      : PhoneLine.{method} {(ApiInformation.IsMethodPresent("Windows.ApplicationModel.Calls.PhoneLine", method) ? "present" : "missing")}");
        Console.WriteLine($"line     : {line.DisplayName} | canDial={line.CanDial}");
        await PrintAudioAsync("audio now");

        PhoneCallManager.CallStateChanged += async (_, _) =>
        {
            Console.WriteLine($"\n{DateTime.Now:HH:mm:ss.fff} state    : active={PhoneCallManager.IsCallActive} incoming={PhoneCallManager.IsCallIncoming}");
            await PrintAudioAsync("audio");
            Console.Write("probe> ");
        };
        Console.WriteLine("Watching calls. Make or take a call on the phone and watch what Windows shows.");
        Console.WriteLine("commands: d <number> dial with the old PhoneLine.Dial | s state | a audio devices | q quit");
        while (true)
        {
            Console.Write("probe> ");
            string? input = Console.ReadLine()?.Trim();
            if (input == null || input == "q") return 0;
            try
            {
                if (input.StartsWith("d ")) { line.Dial(input[2..].Replace(" ", ""), "Pat test"); Console.WriteLine("dial     : sent"); }
                else if (input == "s") Console.WriteLine($"state    : active={PhoneCallManager.IsCallActive} incoming={PhoneCallManager.IsCallIncoming}");
                else if (input == "a") await PrintAudioAsync("audio");
            }
            catch (Exception e) { Console.WriteLine($"error    : {e.GetType().Name}: {e.Message}"); }
        }
    }

    // Bluetooth call audio shows up as "Hands-Free" devices on Windows 10, and only while the phone's call audio is on the laptop.
    static async Task PrintAudioAsync(string label)
    {
        foreach (var (kind, selector) in new[] { ("speaker", MediaDevice.GetAudioRenderSelector()), ("mic", MediaDevice.GetAudioCaptureSelector()) })
        {
            var devices = await DeviceInformation.FindAllAsync(selector);
            var calls = devices.Where(d => d.Name.Contains("Hands-Free", StringComparison.OrdinalIgnoreCase) ||
                                           d.Name.Contains("Headset", StringComparison.OrdinalIgnoreCase) ||
                                           d.Name.Contains("AG Audio", StringComparison.OrdinalIgnoreCase)).Select(d => d.Name).ToList();
            Console.WriteLine($"{label,-9}: {kind}: {(calls.Count == 0 ? "no hands-free device" : string.Join("; ", calls))}");
        }
    }
}
