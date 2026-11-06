using System.Diagnostics;
using System.Text.Json;
using Windows.ApplicationModel.Calls;
using Windows.Devices.Bluetooth;
using Windows.Devices.Enumeration;

// `iphonecall pair`: Pat makes the phone's pairing itself and registers on it straight away, so no other app (Phone Link)
// can register first. Once another app has registered on a pairing, Windows refuses Pat until that pairing is made again.
// A person runs it in a terminal and reads text. The note runs `pair --json` and reads one JSON object per line instead:
// {"event": ..., "text": ...} plus the event's own fields. Both answer on stdin the same way: a number, y or n, an empty
// line to go on, or q to stop.
static class Pairing
{
    const string ClassicProtocol = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}";  // Bluetooth classic: carries calls
    const string MajorKey = "System.Devices.Aep.Bluetooth.Cod.Major";         // the kind a device announces: phone, headphones...
    const uint PhoneMajor = 2;
    const uint PhoneAppearance = 1;
    const int SearchSeconds = 30;
    const int ConnectTries = 4;        // about 20 seconds in all, with the pauses
    const int ConnectPauseSeconds = 5;

    // Phone Link's own program ("Phone Link" in Task Manager). While it runs, an iPhone showed no pairing code twice; with it
    // ended, pairing worked first time (6 Nov). "Mobile devices" (CrossDeviceService) didn't get in the way, so it stays.
    const string PhoneLinkProcess = "PhoneExperienceHost";

    static bool json;
    static readonly object Writing = new();

    sealed record Entry(DeviceInformation Info, bool Le, bool Connected);

    // One step's news: a line of text for a person, or a JSON object for the note.
    static void Tell(string evt, string text, object? fields = null)
    {
        lock (Writing)
        {
            if (!json)
            {
                Console.WriteLine(text);
                return;
            }
            var data = new Dictionary<string, object?> { ["event"] = evt, ["text"] = text };
            if (fields != null)
                foreach (var p in fields.GetType().GetProperties()) data[p.Name] = p.GetValue(fields);
            Console.WriteLine(JsonSerializer.Serialize(data));
        }
    }

    static string? Ask(string evt, string question, object? fields = null)
    {
        if (json) Tell(evt, question, fields);
        else lock (Writing) Console.Write(question);
        return Console.ReadLine()?.Trim();
    }

    static string Selector(string protocol, bool paired) =>
        $"System.Devices.Aep.ProtocolId:=\"{protocol}\" AND System.Devices.Aep.IsPaired:=System.StructuredQueryType.Boolean#{(paired ? "True" : "False")}";

    // A device that doesn't say what it is counts as a phone, so a phone is never hidden.
    static bool MaybePhone(DeviceInformation d, string key, uint phone) =>
        !d.Properties.TryGetValue(key, out var v) || v == null || Convert.ToUInt32(v) == phone;

    // Asking Windows for "paired Bluetooth devices" waits out a 30-second live search before answering, and so does a
    // watcher (both timed 6 Nov). So calls entries come from Pat's own list of hands-free phones (about a second), and
    // notifications entries from Windows' device list, the one Device Manager shows (0.03 s): each paired LE device has a
    // BTHLE\DEV_<address> entry there.
    static async Task<List<Entry>> PairedPhonesAsync()
    {
        var phones = new List<Entry>();
        foreach (var d in await HandsFree.AllAsync())
        {
            var bluetooth = await PhoneWatch.DeviceAsync(d);
            if (bluetooth != null)
                phones.Add(new Entry(bluetooth.DeviceInformation, false, bluetooth.ConnectionStatus == BluetoothConnectionStatus.Connected));
        }
        var names = phones.Select(p => p.Info.Name).ToHashSet(StringComparer.Ordinal);
        var nodes = await DeviceInformation.FindAllAsync("System.Devices.DeviceInstanceId:~<\"BTHLE\\DEV_\"", null,
                                                         DeviceInformationKind.Device);
        foreach (var node in nodes)
        {
            // A device node's id is its instance path, such as BTHLE\Dev_<address>\... (Windows writes "Dev" or "DEV").
            var match = System.Text.RegularExpressions.Regex.Match(node.Id, @"DEV_([0-9A-F]{12})",
                                                                   System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            if (!match.Success) continue;
            ulong address = Convert.ToUInt64(match.Groups[1].Value, 16);
            BluetoothLEDevice? le = null;
            // iPhones use a random LE address, which Windows only finds when told so.
            foreach (var type in new[] { BluetoothAddressType.Public, BluetoothAddressType.Random })
            {
                try { le = await BluetoothLEDevice.FromBluetoothAddressAsync(address, type); }
                catch (Exception) { le = null; }
                if (le != null) break;
            }
            // Listed when it has a phone's name, or says it is a phone. A keyboard isn't.
            if (le == null || !(names.Contains(le.Name) || names.Contains(node.Name) || le.Appearance.Category == PhoneAppearance)) continue;
            phones.Add(new Entry(le.DeviceInformation, true, le.ConnectionStatus == BluetoothConnectionStatus.Connected));
        }
        return phones;
    }

    // When no phone connects: names a phone that is paired only for notifications (Phone Link's setup screen can delete the
    // calls entry and leave this one), so the note can offer to set it up instead of saying it isn't connected.
    public static async Task SayNotificationsOnlyAsync()
    {
        try
        {
            foreach (var group in (await PairedPhonesAsync()).GroupBy(e => e.Info.Name))
                if (group.All(e => e.Le))
                    Console.WriteLine($"phone    : {group.Key} is paired for notifications only, not calls");
        }
        catch (Exception) { }  // only a hint: the failure it explains is reported anyway
    }

    static string Kinds(IEnumerable<Entry> entries)
    {
        bool calls = entries.Any(e => !e.Le), notes = entries.Any(e => e.Le);
        return calls && notes ? "calls and notifications" : calls ? "calls" : "notifications only, no calls";
    }

    // A person's run copies everything to calls\pair-<time>.log and waits for Enter at the end, so nothing is lost.
    // The note's run logs the same way, and the note shows the steps itself.
    public static async Task<int> RunAsync(bool asJson)
    {
        json = asJson;
        if (json)
        {
            Console.OutputEncoding = System.Text.Encoding.UTF8;
            Console.InputEncoding = System.Text.Encoding.UTF8;
        }
        var folder = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "calls"));
        StreamWriter? log = null;
        if (Directory.Exists(folder))
        {
            var path = Path.Combine(folder, $"pair-{DateTime.Now:yyyyMMdd-HHmmss}.log");
            log = new StreamWriter(path) { AutoFlush = true };
            Console.SetOut(new Tee(Console.Out, log));
            Tell("log", $"(also written to {path})");
        }
        int code;
        try { code = await StepsAsync(); }
        catch (Exception e)
        {
            Tell("failed", $"Something went wrong: {e.GetType().Name}: {e.Message.Trim()}");
            code = 1;
        }
        if (!json) Ask("", "\nPress Enter to close.");
        log?.Dispose();
        return code;
    }

    static async Task<int> StepsAsync()
    {
        if (!json) Console.WriteLine("Set up the phone for Pat's calls. Each step prints what happened.\n");

        // 1. Which phone: delete its old entries, both kinds, so the new pairing is one nobody has registered on.
        var paired = await PairedPhonesAsync();
        var names = paired.Select(e => e.Info.Name).Distinct(StringComparer.Ordinal).ToList();
        if (names.Count > 0)
        {
            var listed = names.Select(n => new
            {
                name = n,
                kinds = Kinds(paired.Where(e => e.Info.Name == n)),
                connected = paired.Any(e => e.Info.Name == n && e.Connected),
            }).ToList();
            if (!json)
            {
                Console.WriteLine("Paired phones:");
                for (int i = 0; i < listed.Count; i++) Console.WriteLine($"  {i + 1}. {listed[i].name} ({listed[i].kinds})");
                Console.WriteLine("  0. My phone isn't here");
            }
            if (!int.TryParse(Ask("phones", "Which is your phone? ", new { phones = listed }), out int pick) || pick < 0 || pick > names.Count)
                return Stop();
            if (pick > 0 && !await DeleteAsync(paired.Where(e => e.Info.Name == names[pick - 1]).ToList())) return Stop();
        }
        else Tell("no_phones", "No phone is paired.");

        // 2. Phone Link blocks pairing while it runs.
        EndPhoneLink();

        // 3–4. Find the phone nearby and pair; after a refusal, the phone still holds an old pairing.
        DeviceInformation? info = null;
        var phone = await FindNearbyAsync();
        if (phone == null) return Stop();
        for (int attempt = 1; info == null; attempt++)
        {
            var status = await PairAsync(phone);
            Tell("paired", $"pairing  : {status}", new { status = status.ToString() });
            if (status is DevicePairingResultStatus.Paired or DevicePairingResultStatus.AlreadyPaired)
            {
                info = await TransportForAsync(phone);
                if (info == null) return 1;
                break;
            }
            if (attempt == 1)
            {
                // A phone that still holds an old key for this laptop tries it first and shows no code; once it fails, the phone
                // drops the key, and the next try shows the code (seen on an iPhone, 6 Nov). So the first retry needs nothing from you.
                Tell("retrying", "pairing  : the phone may have tried an old pairing first; trying again...");
                phone = await DeviceInformation.CreateFromIdAsync(phone.Id);  // a fresh copy, so the code question isn't asked twice
                continue;
            }
            if (!json)
                Console.WriteLine($"The phone still refuses. On the phone, open Settings > Bluetooth, tap (i) next to {Environment.MachineName}, " +
                                  "then Forget This Device.");
            if (Ask("refused", "Then press Enter to try again, or q to stop: ", new { laptop = Environment.MachineName })?.ToLowerInvariant() == "q")
                return Stop();
            phone = await DeviceInformation.CreateFromIdAsync(phone.Id);
        }

        // 5. Register at once, before any other app can, then connect and wait for Windows' phone line.
        Tell("connecting", "Connecting Pat to the phone...");
        var store = await PhoneCallManager.RequestStoreAsync();  // open before connecting: see HandsFree.ConnectAnyAsync
        PhoneLine? line = null;
        bool slow = false;
        // Right after pairing, a phone can refuse the call link for a few seconds (an iPhone said connect: False at once and
        // connected by itself a minute later, 6 Nov), so try a few times before saying it isn't connected yet.
        for (int attempt = 1; attempt <= ConnectTries && line == null && !slow; attempt++)
        {
            if (attempt > 1)
            {
                Tell("connecting", "The phone isn't ready yet. Trying again...");
                await Task.Delay(ConnectPauseSeconds * 1000);
            }
            try { line = await HandsFree.ConnectAsync(info, store); }
            catch (TimeoutException) { slow = true; }  // after a fresh pairing, Windows can take over a minute to make the line
        }

        bool registered = PhoneLineTransportDevice.FromId(info.Id).IsRegistered();
        if (!json)
        {
            Console.WriteLine("\nNow paired as: " + Kinds((await PairedPhonesAsync()).Where(e => e.Info.Name == phone.Name)));
            Console.WriteLine($"Pat registered: {(registered ? "yes" : "no")}");
        }
        if (!registered)
        {
            Tell("failed", "Paired, but Windows didn't let Pat use this phone for calls. Try setting it up again.");
            return 1;
        }
        // Registered is what matters: the phone is Pat's now, and the note connects by itself once the phone is ready.
        Tell("done", line != null ? $"Done: Pat can take calls on {info.Name}." :
                     slow ? $"{info.Name} is set up for Pat. Windows is still making its phone line; Pat connects by itself once it's there." :
                            $"{info.Name} is set up for Pat, but isn't connected yet. If Pat doesn't connect within a minute, tap " +
                            $"{Environment.MachineName} in the phone's Settings > Bluetooth.",
             new { name = info.Name, id = info.Id, line = line != null });
        return 0;
    }

    static int Stop()
    {
        Tell("stopped", "Stopped. Nothing else was changed.");
        return 1;
    }

    // False when the person didn't say which of several same-named phones is theirs.
    static async Task<bool> DeleteAsync(List<Entry> entries)
    {
        var classic = entries.Where(e => !e.Le).ToList();
        if (classic.Count > 1)
        {
            // Two phones with the same name: ask instead of deleting both.
            var listed = classic.Select(e => new { name = e.Info.Name, connected = e.Connected }).ToList();
            if (!json)
            {
                Console.WriteLine("Several paired phones have this name:");
                for (int i = 0; i < listed.Count; i++)
                    Console.WriteLine($"  {i + 1}. {listed[i].name}, {(listed[i].connected ? "connected now" : "not connected")}");
            }
            if (!int.TryParse(Ask("same_name", "Which one is yours? ", new { phones = listed }), out int pick) || pick < 1 || pick > classic.Count)
                return false;
            entries = entries.Where(e => e.Le || e == classic[pick - 1]).ToList();
        }
        foreach (var e in entries)
        {
            var result = await e.Info.Pairing.UnpairAsync();
            Tell("deleted", $"deleted  : {e.Info.Name} ({(e.Le ? "notifications" : "calls")} entry): {result.Status}");
        }
        return true;
    }

    // Ends Phone Link only if it's running; says nothing otherwise.
    static void EndPhoneLink()
    {
        foreach (var p in Process.GetProcessesByName(PhoneLinkProcess))
        {
            try
            {
                p.Kill();
                p.WaitForExit(5000);
                Tell("ended_phone_link", $"ended    : Phone Link ({PhoneLinkProcess}), so it doesn't block the pairing");
            }
            catch (Exception e) { Tell("ended_phone_link", $"ended    : couldn't end Phone Link: {e.Message.Trim()}"); }
        }
    }

    // Phones that aren't paired, as Windows finds them. A phone is only visible while its Bluetooth screen is open.
    // The list grows while you watch, and you can choose as soon as your phone shows up. It keeps looking until you do.
    static async Task<DeviceInformation?> FindNearbyAsync()
    {
        if (!json)
        {
            Console.WriteLine("\nOn your phone, open Settings > Bluetooth and keep that screen open.");
            Console.WriteLine("Phones appear below as they're found. Type your phone's number and press Enter, or q to stop.");
        }
        else Tell("searching", "On your phone, open Settings > Bluetooth and keep that screen open.");
        var seen = new Dictionary<string, DeviceInformation>();
        var shown = new List<DeviceInformation>();
        void Show(DeviceInformation d)
        {
            lock (shown)
            {
                if (string.IsNullOrWhiteSpace(d.Name) || !MaybePhone(d, MajorKey, PhoneMajor) || shown.Any(s => s.Id == d.Id)) return;
                shown.Add(d);
                Tell("found", $"  {shown.Count}. {d.Name}", new { number = shown.Count, name = d.Name });
            }
        }
        var watcher = DeviceInformation.CreateWatcher(Selector(ClassicProtocol, false), new[] { MajorKey },
                                                      DeviceInformationKind.AssociationEndpoint);
        watcher.Added += (_, d) => { lock (seen) seen[d.Id] = d; Show(d); };
        watcher.Updated += (_, u) =>
        {
            DeviceInformation? d;
            lock (seen) if (!seen.TryGetValue(u.Id, out d)) return;
            d.Update(u);  // names often arrive a moment after the device
            Show(d);
        };
        watcher.Removed += (_, _) => { };
        watcher.Start();
        try
        {
            var input = Task.Run(Console.ReadLine);
            var hint = Task.Delay(SearchSeconds * 1000);
            while (true)
            {
                if (await Task.WhenAny(input, hint) == hint)
                {
                    lock (shown)
                        if (shown.Count == 0) Tell("not_found_yet", "Can't find it? Check that Bluetooth is on and that screen is open. Still looking...");
                    hint = Task.Delay(Timeout.Infinite);
                    continue;
                }
                var answer = (await input)?.Trim().ToLowerInvariant();
                if (answer is null or "q") return null;
                lock (shown)
                {
                    if (int.TryParse(answer, out int pick) && pick >= 1 && pick <= shown.Count) return shown[pick - 1];
                    if (!json) Console.WriteLine(shown.Count == 0 ? "Nothing found yet. Still looking..." : "Type one of the numbers above.");
                }
                input = Task.Run(Console.ReadLine);
            }
        }
        finally
        {
            try { watcher.Stop(); } catch (Exception) { }
        }
    }

    static async Task<DevicePairingResultStatus> PairAsync(DeviceInformation phone)
    {
        var custom = phone.Pairing.Custom;
        custom.PairingRequested += (_, request) =>
        {
            var deferral = request.GetDeferral();
            try
            {
                switch (request.PairingKind)
                {
                    case DevicePairingKinds.ConfirmPinMatch:
                        // On a retry the phone may show nothing at all: answering n just tries again.
                        var answer = Ask("code", $"Code {request.Pin}. When your phone shows the same code, tap Pair there and type y here. " +
                                                 "No code on the phone after 15 seconds, or a different one? Type n. [y/n] ", new { code = request.Pin });
                        if (answer?.ToLowerInvariant().StartsWith('y') == true) request.Accept();
                        break;
                    case DevicePairingKinds.DisplayPin:
                        Tell("type_code", $"Type this code on your phone: {request.Pin}", new { code = request.Pin });
                        request.Accept();
                        break;
                    case DevicePairingKinds.ConfirmOnly:
                        request.Accept();
                        break;
                    default:
                        Tell("unsupported", $"pairing  : the phone asked for {request.PairingKind}, which Pat doesn't handle yet");
                        break;
                }
            }
            finally { deferral.Complete(); }
        };
        Tell("pairing", $"pairing  : asking {phone.Name}...", new { name = phone.Name });
        var result = await custom.PairAsync(DevicePairingKinds.ConfirmOnly | DevicePairingKinds.ConfirmPinMatch | DevicePairingKinds.DisplayPin,
                                            DevicePairingProtectionLevel.Default);
        return result.Status;
    }

    // The new pairing as a hands-free phone. Windows lists it a few seconds after pairing; Android needs Calls turned on.
    static async Task<DeviceInformation?> TransportForAsync(DeviceInformation phone)
    {
        var bluetooth = await BluetoothDevice.FromIdAsync(phone.Id);
        string address = bluetooth?.BluetoothAddress.ToString("x12") ?? "";
        for (int second = 0; second < 30; second++)
        {
            foreach (var d in await HandsFree.AllAsync())
            {
                string theirs = new string((d.Properties.TryGetValue(HandsFree.AddressKey, out var v) ? v?.ToString() ?? "" : "")
                                           .Where(Uri.IsHexDigit).ToArray()).ToLowerInvariant();
                if (address != "" && theirs == address) return d;
            }
            await Task.Delay(1000);
        }
        Tell("failed", "Paired, but Windows didn't offer this phone for calls. On Android, tap the gear next to this laptop in the " +
                       "phone's Bluetooth settings and turn on Calls, then try again.");
        return null;
    }
}

// Writes to the window and the log file at once.
sealed class Tee(TextWriter screen, TextWriter file) : TextWriter
{
    public override System.Text.Encoding Encoding => screen.Encoding;
    public override void Write(char value) { screen.Write(value); file.Write(value); }
    public override void Write(string? value) { screen.Write(value); file.Write(value); }
    public override void WriteLine(string? value) { screen.WriteLine(value); file.WriteLine(value); }
    public override void Flush() { screen.Flush(); file.Flush(); }
}
