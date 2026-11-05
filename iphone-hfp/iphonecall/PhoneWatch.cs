using Windows.Devices.Bluetooth;
using Windows.Devices.Enumeration;

// For a shell that waits for calls for hours (the sticky note's): says when it should close so the note reconnects to the
// right phone. Uses each phone's Bluetooth connection state, which Windows documents, not its name or its phone line.
sealed class PhoneWatch
{
    private static readonly TimeSpan Steady = TimeSpan.FromSeconds(5); // a phone that drops and comes back within this never left
    private readonly BluetoothDevice? _using;
    private readonly BluetoothDevice? _preferred;
    private readonly string _usingName;
    private readonly string _preferredName;
    // Only a chosen phone that was away when the line started can "come back": one that was connected but still lost the
    // line to another phone would otherwise close the shell again and again.
    private readonly bool _preferredWasAway;
    private DateTime? _since;

    private PhoneWatch(BluetoothDevice? usingPhone, string usingName, BluetoothDevice? preferred, string preferredName)
    {
        _using = usingPhone;
        _usingName = usingName;
        _preferred = preferred;
        _preferredName = preferredName;
        _preferredWasAway = preferred?.ConnectionStatus != BluetoothConnectionStatus.Connected;
    }

    // `preferred` is the phone chosen in Pat's settings, when the call line had to fall back to another one.
    public static async Task<PhoneWatch> CreateAsync(DeviceInformation usingPhone, DeviceInformation? preferred)
    {
        var current = await DeviceAsync(usingPhone);
        var wanted = preferred == null || preferred.Id == usingPhone.Id ? null : await DeviceAsync(preferred);
        return new PhoneWatch(current, usingPhone.Name, wanted, preferred?.Name ?? "");
    }

    public static async Task<BluetoothDevice?> DeviceAsync(DeviceInformation info)
    {
        try
        {
            if (!info.Properties.TryGetValue(HandsFree.AddressKey, out var value) || value == null) return null;
            string hex = value.ToString()!.Replace(":", "").Replace("-", "");
            return await BluetoothDevice.FromBluetoothAddressAsync(Convert.ToUInt64(hex, 16)).AsTask().WaitAsync(TimeSpan.FromSeconds(10));
        }
        catch (Exception) { return null; }
    }

    // Why the shell should close now, or null. Only asked while no call is running.
    public string? Reason()
    {
        string? reason = null;
        if (_using?.ConnectionStatus == BluetoothConnectionStatus.Disconnected) reason = $"phone disconnected: {_usingName}";
        else if (_preferredWasAway && _preferred?.ConnectionStatus == BluetoothConnectionStatus.Connected) reason = $"chosen phone is back: {_preferredName}";
        if (reason == null)
        {
            _since = null;
            return null;
        }
        _since ??= DateTime.UtcNow;
        return DateTime.UtcNow - _since >= Steady ? reason : null;
    }
}
