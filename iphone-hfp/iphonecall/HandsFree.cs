using System.Runtime.InteropServices;
using Windows.ApplicationModel.Calls;
using Windows.Devices.Enumeration;
using System.Text.Json;

// Finds the paired phone and brings up Windows' hands-free link to it. The order of the steps and
// the manifest entries both matter; read "Things that matter" in ..\README.md before changing them.
static class HandsFree
{
    private const string AddressKey = "System.DeviceInterface.Bluetooth.DeviceAddress";

    private static async Task<IReadOnlyList<DeviceInformation>> AllAsync() =>
        await DeviceInformation.FindAllAsync(
            PhoneLineTransportDevice.GetDeviceSelector(PhoneLineTransport.Bluetooth), new[] { AddressKey });

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

    public static async Task<DeviceInformation?> FindAsync(string? nameHint = null, string? deviceId = null) =>
        PhoneSelection.Choose(await AllAsync(), d => d.Name, d => d.Id, nameHint, deviceId);

    public static void Unregister(DeviceInformation info) => PhoneLineTransportDevice.FromId(info.Id).UnregisterApp();

    // Prints each step on its own line (they fail independently, and which one fails is the
    // diagnosis) and returns the phone's line once the link is up, or null.
    public static async Task<PhoneLine?> ConnectAsync(DeviceInformation info)
    {
        var device = PhoneLineTransportDevice.FromId(info.Id);
        // Open the call store first: opened after ConnectAsync in the same process, it never returns.
        var store = await Timed(PhoneCallManager.RequestStoreAsync().AsTask(), 15, "phone call store");

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
            Console.WriteLine("Not connected. On the iPhone, open Settings > Bluetooth and tap this laptop, then retry.");
            return null;
        }

        var line = await WaitForLineAsync(store, device.DeviceId);
        if (line == null) Console.WriteLine("Connected, but Windows did not create a phone line for this phone.");
        return line;
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
            var watcher = store.RequestLineWatcher();
            var ids = new List<Guid>();
            var done = new TaskCompletionSource<bool>();
            watcher.LineAdded += (_, e) => { lock (ids) ids.Add(e.LineId); };
            watcher.EnumerationCompleted += (_, _) => done.TrySetResult(true);
            watcher.Stopped += (_, _) => done.TrySetResult(false);
            watcher.Start();
            await Task.WhenAny(done.Task, Task.Delay(5000));
            try { watcher.Stop(); } catch (COMException) { }

            List<Guid> snapshot;
            lock (ids) snapshot = ids.ToList();
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
        try { return await step(); }
        catch (Exception e) { return $"failed: {e.GetType().Name} (0x{e.HResult:X8}) {e.Message.Trim()}"; }
    }

    // Some of these system calls can hang instead of failing; turn a hang into a clear error.
    private static async Task<T> Timed<T>(Task<T> task, int seconds, string what)
    {
        if (await Task.WhenAny(task, Task.Delay(seconds * 1000)) != task)
            throw new TimeoutException($"{what} did not answer within {seconds}s");
        return await task;
    }
}
