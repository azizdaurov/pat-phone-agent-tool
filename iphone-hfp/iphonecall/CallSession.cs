using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Windows.ApplicationModel.Calls;

// Call control on one phone line, plus a monitor that prints call changes and moves each new
// call's audio to the laptop. Windows only plays call audio on the laptop after that switch.
sealed class CallSession
{
    private readonly PhoneLine _line;
    private readonly Dictionary<string, (PhoneCallStatus Status, PhoneCallAudioDevice Audio)> _seen = new();
    private readonly Dictionary<string, (DateTime Last, int Tries)> _moveTries = new();
    private bool? _chosenPhone; // set by 'l' or 'p' for the current call
    private readonly DateTime _started = DateTime.UtcNow;
    private bool _sawCall;
    private DateTime? _quietSince;

    public CallSession(PhoneLine line) => _line = line;

    // Off for the shell a call's owner doesn't need the laptop in: the window Windows opens by itself
    // for a call, and --stay-on-phone. Those leave a call's audio where it is unless told otherwise.
    public bool MoveToLaptop { get; init; } = true;

    // Set for the windows Windows opens by itself for a call: exit 3 s after the last call ends,
    // or after a minute if no call ever shows up.
    public bool CloseAfterCalls { get; init; }

    // With --follow-phone: closes the shell, while no call runs, once the phone it should be on has changed.
    public PhoneWatch? Watch { get; init; }

    // Windows keeps a finished call in this "active" list for minutes, with status Ended.
    private IReadOnlyList<PhoneCall> ActiveCalls() =>
        _line.GetAllActivePhoneCalls().AllActivePhoneCalls?.Where(c => c.Status != PhoneCallStatus.Ended).ToList()
        ?? new List<PhoneCall>();

    private static bool IsLive(PhoneCall call) =>
        call.Status is PhoneCallStatus.Dialing or PhoneCallStatus.Talking or PhoneCallStatus.Held;

    private static string Describe(PhoneCall call)
    {
        var info = call.GetPhoneCallInfo();
        string who = string.IsNullOrEmpty(info.DisplayName) ? info.PhoneNumber : $"{info.DisplayName} ({info.PhoneNumber})";
        return $"{info.CallDirection} {who}: {call.Status}, audio={call.AudioDevice}, muted={call.IsMuted}";
    }

    private PhoneCall? Find(params PhoneCallStatus[] statuses) =>
        ActiveCalls().FirstOrDefault(c => statuses.Contains(c.Status));

    public void PrintStatus()
    {
        Console.WriteLine($"line     : {_line.DisplayName} | canDial={_line.CanDial}");
        var calls = ActiveCalls();
        if (calls.Count == 0) Console.WriteLine("calls    : none");
        foreach (var call in calls) Console.WriteLine($"call     : {Describe(call)}");
    }

    public void Dial(string number)
    {
        number = number.Replace(" ", "");
        if (!Regex.IsMatch(number, @"^\+?[0-9*#]+$"))
            throw new ArgumentException($"not a dialable number: '{number}'");
        var result = _line.DialWithResult(number, number);
        Console.WriteLine($"dial {number}: {result.DialCallStatus}");
    }

    public async Task AnswerAsync()
    {
        var call = Find(PhoneCallStatus.Incoming) ?? throw new InvalidOperationException("no incoming call");
        Console.WriteLine($"answer: {await call.AcceptIncomingAsync()}");
    }

    public async Task HangUpAsync()
    {
        var incoming = Find(PhoneCallStatus.Incoming);
        if (incoming != null)
        {
            Console.WriteLine($"reject: {await incoming.RejectIncomingAsync()}");
            return;
        }
        var call = Find(PhoneCallStatus.Talking, PhoneCallStatus.Dialing, PhoneCallStatus.Held)
                   ?? throw new InvalidOperationException("no call to hang up");
        Console.WriteLine($"hang up: {await call.EndAsync()}");
    }

    public async Task ToggleMuteAsync()
    {
        var call = Find(PhoneCallStatus.Talking, PhoneCallStatus.Held) ?? throw new InvalidOperationException("no active call");
        var status = call.IsMuted ? await call.UnmuteAsync() : await call.MuteAsync();
        Console.WriteLine($"mute: {status} (muted={call.IsMuted})");
    }

    public async Task RouteAudioAsync(PhoneCallAudioDevice target)
    {
        var call = ActiveCalls().FirstOrDefault(c => IsLive(c) || c.Status == PhoneCallStatus.Incoming)
                   ?? throw new InvalidOperationException("no call");
        _chosenPhone = target == PhoneCallAudioDevice.RemoteDevice;
        Console.WriteLine($"audio -> {target}: {await call.ChangeAudioDeviceAsync(target)}");
    }

    // Polls the line twice a second so incoming calls and status changes show up in the terminal.
    public async Task MonitorAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            try
            {
                var calls = ActiveCalls();
                var current = new HashSet<string>();
                foreach (var call in calls)
                {
                    current.Add(call.CallId);
                    var state = (call.Status, call.AudioDevice);
                    if (_seen.TryGetValue(call.CallId, out var last) && last == state) continue;
                    _seen[call.CallId] = state;
                    string hint = call.Status == PhoneCallStatus.Incoming ? "   (type 'a' to answer, 'h' to reject)" : "";
                    Console.WriteLine($"\n-- {Describe(call)}{hint}");
                }
                foreach (var gone in _seen.Keys.Where(k => !current.Contains(k)).ToList())
                {
                    _seen.Remove(gone);
                    _moveTries.Remove(gone);
                    if (current.Count == 0) _chosenPhone = null;
                    Console.WriteLine($"\n-- call ended ({current.Count} active)");
                }

                foreach (var call in calls.Where(IsLive))
                    await KeepAudioOnLaptopAsync(call);

                if (CloseAfterCalls) CloseWhenIdle(calls.Count > 0);
                if (calls.Count == 0 && Watch?.Reason() is string reason)
                {
                    Console.WriteLine($"\n-- {reason}; closing so the line can reconnect");
                    Environment.Exit(3);
                }
            }
            catch (COMException) { }
            try { await Task.Delay(500, token); } catch (TaskCanceledException) { }
        }
    }

    private void CloseWhenIdle(bool anyCall)
    {
        var now = DateTime.UtcNow;
        if (anyCall)
        {
            _sawCall = true;
            _quietSince = null;
            return;
        }
        _quietSince ??= now;
        bool callOver = _sawCall && now - _quietSince > TimeSpan.FromSeconds(3);
        bool noCallCame = !_sawCall && now - _started > TimeSpan.FromMinutes(1);
        if (callOver || noCallCame) Environment.Exit(0);
    }

    // The switch can report Succeeded and still leave the call on the phone, so keep trying every
    // 2 s until the call really shows LocalDevice. 'p' stops this, for taking a call on the phone.
    private async Task KeepAudioOnLaptopAsync(PhoneCall call)
    {
        bool stayOnPhone = _chosenPhone ?? !MoveToLaptop;
        if (stayOnPhone || call.AudioDevice == PhoneCallAudioDevice.LocalDevice) return;
        var now = DateTime.UtcNow;
        _moveTries.TryGetValue(call.CallId, out var tried);
        if (tried.Tries > 0 && now - tried.Last < TimeSpan.FromSeconds(2)) return;
        _moveTries[call.CallId] = (now, tried.Tries + 1);
        try
        {
            var result = await call.ChangeAudioDeviceAsync(PhoneCallAudioDevice.LocalDevice);
            Console.WriteLine($"\n-- audio -> laptop, try {tried.Tries + 1}: {result}");
        }
        catch (COMException e) { Console.WriteLine($"\n-- audio -> laptop failed: {e.Message.Trim()}"); }
    }
}
