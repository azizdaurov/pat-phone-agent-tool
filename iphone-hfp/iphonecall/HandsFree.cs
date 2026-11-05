using System.Runtime.InteropServices;
using Windows.ApplicationModel.Calls;
using Windows.Devices.Enumeration;
using System.Text.Json;

// Finds the paired phone and brings up Windows' hands-free link to it. The order of the steps and
// the manifest entries both matter; read "Things that matter" in ..\README.md before changing them.
static class HandsFree
{
    public const string AddressKey = "System.DeviceInterface.Bluetooth.DeviceAddress";

    private static async Task<IReadOnlyList<DeviceInformation>> AllAsync() =>
        await DeviceInformation.FindAllAsync(
            PhoneLineTransportDevice.GetDeviceSelector(PhoneLineTransport.Bluetooth), new[] { AddressKey }.Concat(BluetoothAudio.Properties))
            .AsTask().WaitAsync(TimeSpan.FromSeconds(10));

    public static async Task ListAsync()
    {
        foreach (var d in await AllAsync())
        {
            var device = PhoneLineTransportDevice.FromId(d.Id);
            Console.WriteLine($"{d.Name,-30} address={d.Properties[AddressKey]} registered={device.IsRegistered()}");
        }
    }

    public static async Task ListJsonAsync() =>
        Console.WriteLine(JsonSerializer.Serialize((await AllAsync()).Select(d => new { id = d.Id, name = d.Name })));

    // With no phone chosen and several paired, the one that owns Windows' default phone line: the phone that connected last.
    public static async Task<DeviceInformation?> FindAsync(string? nameHint = null, string? deviceId = null)
    {
        var all = await AllAsync();
        if (string.IsNullOrEmpty(nameHint) && string.IsNullOrEmpty(deviceId) && all.Count > 1)
        {
            var active = await ActiveTransportIdAsync();
            var match = active == null ? null : all.FirstOrDefault(d =>
                string.Equals(PhoneLineTransportDevice.FromId(d.Id).DeviceId, active, StringComparison.OrdinalIgnoreCase));
            if (match != null) return match;
        }
        return PhoneSelection.Choose(all, d => d.Name, d => d.Id, nameHint, deviceId);
    }

    private static async Task<string?> ActiveTransportIdAsync()
    {
        try
        {
            var store = await Timed(PhoneCallManager.RequestStoreAsync().AsTask(), 15, "phone call store");
            var id = await Timed(store.GetDefaultLineAsync().AsTask(), 10, "default line");
            var line = await Timed(PhoneLine.FromIdAsync(id).AsTask(), 10, "default line lookup");
            return line.TransportDeviceId;
        }
        catch (Exception) { return null; }
    }

    public static void Unregister(DeviceInformation info) => PhoneLineTransportDevice.FromId(info.Id).UnregisterApp();

    // The chosen phone first. If it can't be reached, such as one that was switched off or left in a drawer, each other
    // paired phone that has a Windows phone line, so whichever phone is here takes the call.
    // Tries the phones in PhoneSelection.Order: one that is connected before one that isn't, whatever Windows' default says.
    // Returns the line and the phone it belongs to, or (null, null).
    public static async Task<(PhoneLine? line, DeviceInformation? phone)> ConnectAnyAsync(DeviceInformation first)
    {
        // Open the call store first, and only once: opened after ConnectAsync in the same process, it never returns.
        var store = await Timed(PhoneCallManager.RequestStoreAsync().AsTask(), 15, "phone call store");
        var all = await AllAsync();
        var order = PhoneSelection.Order(await CandidatesAsync(all, store, first));
        string? tried = null;
        foreach (var candidate in order)
        {
            var info = all.First(d => d.Id == candidate.Id);
            if (tried != null) Console.WriteLine($"phone    : {tried} isn't reachable, trying {info.Name}");
            var line = await ConnectAsync(info, store);
            if (line != null) return (line, info);
            tried = info.Name;
        }
        return (null, null);
    }

    // What Windows says about each paired phone: Bluetooth connection, phone line, default line. Reads only.
    private static async Task<List<PhoneSelection.Candidate>> CandidatesAsync(IReadOnlyList<DeviceInformation> all, PhoneCallStore store,
                                                                            DeviceInformation? first)
    {
        var transports = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var (ids, _) = ListLineIds(store, 5);
        foreach (var id in ids)
        {
            try { transports.Add((await Timed(PhoneLine.FromIdAsync(id).AsTask(), 10, "phone line lookup")).TransportDeviceId); }
            catch (Exception) { }
        }
        string? defaultTransport = null;
        try
        {
            var defaultId = await Timed(store.GetDefaultLineAsync().AsTask(), 10, "default line");
            defaultTransport = (await Timed(PhoneLine.FromIdAsync(defaultId).AsTask(), 10, "default line lookup")).TransportDeviceId;
        }
        catch (Exception) { }
        var candidates = new List<PhoneSelection.Candidate>();
        foreach (var d in all)
        {
            string transport = PhoneLineTransportDevice.FromId(d.Id).DeviceId;
            bool connected = (await PhoneWatch.DeviceAsync(d))?.ConnectionStatus == Windows.Devices.Bluetooth.BluetoothConnectionStatus.Connected;
            candidates.Add(new(d.Id, d.Name, connected, transports.Contains(transport), d.Id == first?.Id,
                               string.Equals(transport, defaultTransport, StringComparison.OrdinalIgnoreCase)));
        }
        return candidates;
    }

    // `iphonecall phones`: each paired phone, whether it is connected, whether it has a phone line, which line is Windows'
    // default, and the order Pat would try them in. Reads only.
    public static async Task PhonesAsync(DeviceInformation? first)
    {
        var store = await Timed(PhoneCallManager.RequestStoreAsync().AsTask(), 15, "phone call store");
        var all = await AllAsync();
        var candidates = await CandidatesAsync(all, store, first);
        Console.WriteLine($"{"phone",-28} {"connected",-10} {"line",-6} {"default",-8} first");
        foreach (var c in candidates)
            Console.WriteLine($"{c.Name,-28} {(c.Connected ? "yes" : "no"),-10} {(c.HasLine ? "yes" : "no"),-6} {(c.Default ? "yes" : ""),-8} {(c.First ? "yes" : "")}");
        Console.WriteLine("Pat tries: " + string.Join(", then ", PhoneSelection.Order(candidates).Select(c => c.Name)));
    }

    // Prints each step on its own line (they fail independently, and which one fails is the
    // diagnosis) and returns the phone's line once the link is up, or null.
    private static async Task<PhoneLine?> ConnectAsync(DeviceInformation info, PhoneCallStore store)
    {
        var device = PhoneLineTransportDevice.FromId(info.Id);

        Console.WriteLine($"phone    : {info.Name}");
        Console.WriteLine($"access   : {await StepAsync(async () => (await device.RequestAccessAsync()).ToString())}");
        string registered = await StepAsync(() =>
        {
            if (!device.IsRegistered()) device.RegisterApp();
            return Task.FromResult($"registered={device.IsRegistered()}");
        });
        Console.WriteLine($"register : {registered}");
        bool connected = false;
        Console.WriteLine($"connect  : {await StepAsync(async () => (connected = await device.ConnectAsync()).ToString())}");
        if (!connected)
        {
            // Windows still has a working line for this phone but won't connect us: another app took the phone's call link
            // and keeps it, even after that app quits. Seen 5 Nov 2026, when Phone Link was woken in the background for a call.
            if (await HasLineAsync(store, device.DeviceId))
            {
                Console.WriteLine($"held     : {HeldByAnotherApp}. Windows has this phone's call line, but another app holds it, usually Phone Link.");
                Console.WriteLine("Close Phone Link and stop it running in the background, then remove the phone in Bluetooth settings and pair it again.");
                return null;
            }
            Console.WriteLine("Not connected. On your phone, open Bluetooth settings, connect to this PC, and allow calls when prompted, then retry.");
            return null;
        }

        Console.WriteLine("line     : waiting for Windows phone line");
        var line = await Timed(WaitForLineAsync(store, device.DeviceId), 30, "Windows phone line creation");
        if (line == null) Console.WriteLine("Connected, but Windows did not create a phone line for this phone. Turn on Settings > " +
                                            "Bluetooth & devices > Mobile devices > 'Allow this PC to access your mobile devices', then retry.");
        return line;
    }

    // Pat's PhoneLine.TAKEN looks for this word.
    public const string HeldByAnotherApp = "HeldByAnotherApp";

    // Whether Windows has a phone line for this phone right now. Reads only, and doesn't wait for one to appear.
    private static async Task<bool> HasLineAsync(PhoneCallStore store, string transportDeviceId)
    {
        var (ids, _) = ListLineIds(store, 5);
        foreach (var id in ids)
        {
            try
            {
                var line = await Timed(PhoneLine.FromIdAsync(id).AsTask(), 10, "phone line lookup");
                if (string.Equals(line.TransportDeviceId, transportDeviceId, StringComparison.OrdinalIgnoreCase)) return true;
            }
            catch (Exception) { }
        }
        return false;
    }

    // Windows creates the PhoneLine shortly after the link comes up: try the default line, then watch.
    private static async Task<PhoneLine?> WaitForLineAsync(PhoneCallStore store, string transportDeviceId)
    {
        bool IsOurs(PhoneLine line) =>
            string.Equals(line.TransportDeviceId, transportDeviceId, StringComparison.OrdinalIgnoreCase);

        try
        {
            var defaultId = await Timed(store.GetDefaultLineAsync().AsTask(), 10, "default line");
            var line = await Timed(PhoneLine.FromIdAsync(defaultId).AsTask(), 10, "phone line lookup");
            if (IsOurs(line)) return line;
        }
        catch (COMException) { }

        for (int attempt = 1; attempt <= 10; attempt++)
        {
            var (snapshot, _) = ListLineIds(store, 5);
            Console.WriteLine($"line scan: {snapshot.Count} visible line(s)");
            foreach (var id in snapshot)
            {
                var line = await Timed(PhoneLine.FromIdAsync(id).AsTask(), 10, "phone line lookup");
                if (IsOurs(line)) return line;
            }
            await Task.Delay(1000);
        }
        return null;
    }

    private static async Task<string> StepAsync(Func<Task<string>> step)
    {
        try { return await Timed(step(), 20, "Bluetooth phone setup"); }
        catch (Exception e) { return $"failed: {e.GetType().Name} (0x{e.HResult:X8}) {e.Message.Trim()}"; }
    }

    // Read-only: every phone line Windows has, and the id each paired phone would need to match.
    // Tells "no line exists" apart from "a line exists but isn't matched to this phone".
    public static async Task LinesAsync()
    {
        foreach (var d in await AllAsync())
        {
            var device = PhoneLineTransportDevice.FromId(d.Id);
            Console.WriteLine($"phone    : {d.Name} | transport id {device.DeviceId} | registered={device.IsRegistered()}");
        }
        var store = await Timed(PhoneCallManager.RequestStoreAsync().AsTask(), 15, "phone call store");
        Console.WriteLine("store    : open");
        try
        {
            var defaultId = await Timed(store.GetDefaultLineAsync().AsTask(), 10, "default line");
            Console.WriteLine($"default  : {defaultId}");
            var line = await Timed(PhoneLine.FromIdAsync(defaultId).AsTask(), 10, "default line lookup");
            Console.WriteLine($"  it is  : '{line.DisplayName}' transport={line.Transport} transport id={line.TransportDeviceId} " +
                              $"network={line.NetworkState} canDial={line.CanDial}");
        }
        catch (Exception e) { Console.WriteLine($"default  : none ({e.GetType().Name}: {e.Message.Trim()})"); }

        var (ids, finished) = ListLineIds(store, 10);
        var snapshot = ids;
        Console.WriteLine($"lines    : {snapshot.Count}{(finished ? "" : " (the list didn't finish within 10s)")}");
        foreach (var id in snapshot)
        {
            try
            {
                var line = await Timed(PhoneLine.FromIdAsync(id).AsTask(), 10, "phone line lookup");
                Console.WriteLine($"  line {id}: '{line.DisplayName}' transport={line.Transport} transport id={line.TransportDeviceId} " +
                                  $"network={line.NetworkState} canDial={line.CanDial}");
            }
            catch (Exception e) { Console.WriteLine($"  line {id}: couldn't open ({e.GetType().Name}: {e.Message.Trim()})"); }
        }
    }

    // The line watcher, on a thread of its own: created on the main thread, RequestLineWatcher can block the whole process.
    // Returns the line ids it reported, and whether it finished listing before the deadline.
    private static (List<Guid> ids, bool finished) ListLineIds(PhoneCallStore store, int seconds)
    {
        var ids = new List<Guid>();
        var done = new ManualResetEventSlim(false);
        bool finished = false;
        var thread = new Thread(() =>
        {
            try
            {
                var watcher = store.RequestLineWatcher();
                watcher.LineAdded += (_, e) => { lock (ids) ids.Add(e.LineId); };
                watcher.EnumerationCompleted += (_, _) => { finished = true; done.Set(); };
                watcher.Stopped += (_, _) => done.Set();
                watcher.Start();
                done.Wait(TimeSpan.FromSeconds(seconds));
                try { watcher.Stop(); } catch (COMException) { }
            }
            catch (Exception e) { Console.WriteLine($"lines    : watcher failed ({e.GetType().Name}: {e.Message.Trim()})"); }
            finally { done.Set(); }
        }) { IsBackground = true };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join(TimeSpan.FromSeconds(seconds + 5));
        lock (ids) return (ids.ToList(), finished);
    }

    // Some of these system calls can hang instead of failing; turn a hang into a clear error.
    private static async Task<T> Timed<T>(Task<T> task, int seconds, string what)
    {
        if (await Task.WhenAny(task, Task.Delay(seconds * 1000)) != task)
            throw new TimeoutException($"{what} did not answer within {seconds}s");
        return await task;
    }
}
