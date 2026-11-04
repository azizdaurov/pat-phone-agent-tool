using System.Runtime.InteropServices;
using System.Text;
using Windows.Devices.Enumeration;
using Windows.Media.Devices;

// Read-only inventory. This never requests a call store, registers a phone, or opens an audio stream.
static class BluetoothAudio
{
    public static readonly string[] Properties = { "System.Devices.ContainerId", "System.Devices.DeviceInstanceId" };

    public static async Task<object> InventoryAsync(DeviceInformation? phone)
    {
        var render = DeviceInformation.FindAllAsync(MediaDevice.GetAudioRenderSelector(), Properties).AsTask();
        var capture = DeviceInformation.FindAllAsync(MediaDevice.GetAudioCaptureSelector(), Properties).AsTask();
        await Task.WhenAll(render, capture).WaitAsync(TimeSpan.FromSeconds(12));
        var endpoints = render.Result.Concat(capture.Result).Where(d => d.IsEnabled).DistinctBy(d => d.Id).Select(d =>
        {
            var identity = Identity(d);
            return new { name = d.Name, id = d.Id, container_id = identity.Container,
                         instance_ids = identity.Instances, services = identity.Services };
        }).ToArray();
        var selected = phone == null ? null : Identity(phone);
        return new { schema_version = 1,
            phone = phone == null ? null : new { id = phone.Id, container_id = selected!.Container,
                                                 instance_id = selected.Instances.FirstOrDefault() },
            endpoints };
    }

    private sealed record DeviceIdentity(string? Container, string[] Instances, string[] Services);

    private static DeviceIdentity Identity(DeviceInformation device)
    {
        string? Property(string key) => device.Properties.TryGetValue(key, out var value) ? value?.ToString() : null;
        string? instance = Property("System.Devices.DeviceInstanceId") ?? InterfaceInstance(device.Id);
        string? container = ValidContainer(Property("System.Devices.ContainerId"));
        var instances = new List<string>();
        var services = new List<string>();
        if (!string.IsNullOrWhiteSpace(instance))
        {
            instances.Add(instance);
            if (CM_Locate_DevNodeW(out uint node, instance, 0) == 0)
            {
                // Only the endpoint's own container is used; a shared Bluetooth adapter/PC ancestor isn't a phone identity.
                container ??= NodeGuid(node, new PropertyKey("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c", 2));
                for (int depth = 0; depth < 12; depth++)
                {
                    var service = NodeString(node, new PropertyKey("a45c254e-df1c-4efd-8020-67d146a850e0", 6));
                    if (!string.IsNullOrWhiteSpace(service)) services.Add(service);
                    if (CM_Get_Parent(out uint parent, node, 0) != 0 || parent == node) break;
                    // Stop at the Bluetooth adapter: its common parent must not join unrelated peripherals.
                    var parentService = NodeString(parent, new PropertyKey("a45c254e-df1c-4efd-8020-67d146a850e0", 6));
                    if (string.Equals(parentService, "BTHUSB", StringComparison.OrdinalIgnoreCase)) break;
                    var buffer = new StringBuilder(512);
                    if (CM_Get_Device_IDW(parent, buffer, buffer.Capacity, 0) != 0) break;
                    if (instances.Contains(buffer.ToString(), StringComparer.OrdinalIgnoreCase)) break;
                    instances.Add(buffer.ToString());
                    node = parent;
                }
            }
        }
        return new(container, instances.ToArray(), services.Distinct(StringComparer.OrdinalIgnoreCase).ToArray());
    }

    private static string? ValidContainer(string? value) =>
        Guid.TryParse(value, out var guid) && guid != Guid.Empty ? guid.ToString("D") : null;

    [StructLayout(LayoutKind.Sequential)]
    private struct PropertyKey
    {
        public Guid Id;
        public uint Pid;
        public PropertyKey(string id, uint pid) { Id = new Guid(id); Pid = pid; }
    }

    private static string? InterfaceInstance(string id)
    {
        var key = new PropertyKey("78c34fc8-104a-4aca-9ea4-524d52996e57", 256);
        uint bytes = 0;
        CM_Get_Device_Interface_PropertyW(id, ref key, out _, null, ref bytes, 0);
        if (bytes == 0 || bytes > 65536) return null;
        var buffer = new byte[bytes];
        return CM_Get_Device_Interface_PropertyW(id, ref key, out uint type, buffer, ref bytes, 0) == 0 && type == 0x12
            ? Encoding.Unicode.GetString(buffer).TrimEnd('\0') : null;
    }

    private static string? NodeString(uint node, PropertyKey key)
    {
        var buffer = new byte[2048];
        uint bytes = (uint)buffer.Length;
        return CM_Get_DevNode_PropertyW(node, ref key, out uint type, buffer, ref bytes, 0) == 0 && type == 0x12
            ? Encoding.Unicode.GetString(buffer, 0, (int)bytes).TrimEnd('\0') : null;
    }

    private static string? NodeGuid(uint node, PropertyKey key)
    {
        var buffer = new byte[16];
        uint bytes = 16;
        return CM_Get_DevNode_PropertyW(node, ref key, out uint type, buffer, ref bytes, 0) == 0 && type == 0x0d && bytes == 16
            ? ValidContainer(new Guid(buffer).ToString()) : null;
    }

    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Get_Device_Interface_PropertyW(string id, ref PropertyKey key, out uint type, byte[]? buffer, ref uint bytes, uint flags);
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Locate_DevNodeW(out uint node, string id, uint flags);
    [DllImport("cfgmgr32.dll")]
    private static extern uint CM_Get_Parent(out uint parent, uint node, uint flags);
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Get_Device_IDW(uint node, StringBuilder buffer, int length, uint flags);
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Get_DevNode_PropertyW(uint node, ref PropertyKey key, out uint type, byte[] buffer, ref uint bytes, uint flags);
}
