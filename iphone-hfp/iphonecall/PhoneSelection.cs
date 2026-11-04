// Selection is independent of Bluetooth names, country or Windows' display language.
static class PhoneSelection
{
    public static T? Choose<T>(IReadOnlyList<T> devices, Func<T, string> name, Func<T, string> id,
                               string? nameHint = null, string? deviceId = null) where T : class
    {
        var matches = devices.Where(d => !string.IsNullOrEmpty(deviceId)
            ? string.Equals(id(d), deviceId, StringComparison.OrdinalIgnoreCase)
            : string.IsNullOrEmpty(nameHint) || name(d).Contains(nameHint, StringComparison.OrdinalIgnoreCase)).ToList();
        if (matches.Count > 1)
            throw new InvalidOperationException("Several paired phones match. Choose a phone in Pat's 'Your name, region and phone' settings, or use --device-id.");
        return matches.Count == 1 ? matches[0] : null;
    }
}
