using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

const int ContractVersion = 1;
const int MaxLineBytes = 1_048_576;

var token = Environment.GetEnvironmentVariable("JARVIS_POLYGLOT_TOKEN") ?? "";
if (token.Length < 32)
{
    Console.Error.WriteLine("JARVIS_POLYGLOT_TOKEN must contain at least 32 characters.");
    return 2;
}

var portText = Environment.GetEnvironmentVariable("JARVIS_SIDECAR_PORT") ?? "18762";
if (!int.TryParse(portText, out var port) || port is < 1 or > 65535)
{
    Console.Error.WriteLine("JARVIS_SIDECAR_PORT must be between 1 and 65535.");
    return 2;
}

var listener = new TcpListener(IPAddress.Loopback, port);
listener.Start();
Console.Error.WriteLine($"jarvis dotnet sidecar listening on 127.0.0.1:{port} (contract v{ContractVersion})");
while (true)
{
    using var client = await listener.AcceptTcpClientAsync();
    try
    {
        await HandleClient(client, token);
    }
    catch (Exception exception)
    {
        Console.Error.WriteLine($"jarvis dotnet sidecar request failed: {exception.GetType().Name}");
    }
}

static async Task HandleClient(TcpClient client, string expectedToken)
{
    client.ReceiveTimeout = 2000;
    client.SendTimeout = 2000;
    await using var stream = client.GetStream();
    using var writer = new StreamWriter(stream, new UTF8Encoding(false), 4096, leaveOpen: true)
    {
        AutoFlush = true,
        NewLine = "\n",
    };

    var line = await ReadLineLimited(stream);
    if (line is null || Encoding.UTF8.GetByteCount(line) > MaxLineBytes)
    {
        return;
    }

    using var nullDocument = JsonDocument.Parse("null");
    JsonDocument document;
    try
    {
        document = JsonDocument.Parse(line);
    }
    catch (JsonException)
    {
        await writer.WriteLineAsync(JsonSerializer.Serialize(
            Error(nullDocument.RootElement.Clone(), -32700, "parse error")));
        return;
    }
    using var documentScope = document;
    var root = document.RootElement;
    var id = root.ValueKind == JsonValueKind.Object
        && root.TryGetProperty("id", out var requestId)
        ? requestId.Clone()
        : nullDocument.RootElement.Clone();
    object response;
    if (root.ValueKind != JsonValueKind.Object
        || !root.TryGetProperty("jsonrpc", out var rpcVersion)
        || rpcVersion.ValueKind != JsonValueKind.String
        || rpcVersion.GetString() != "2.0")
    {
        response = Error(id, -32600, "invalid JSON-RPC request");
    }
    else if (!root.TryGetProperty("params", out var parameters) || parameters.ValueKind != JsonValueKind.Object)
    {
        response = Error(id, -32600, "params must be an object");
    }
    else if (!parameters.TryGetProperty("token", out var suppliedToken)
        || suppliedToken.ValueKind != JsonValueKind.String
        || suppliedToken.GetString() != expectedToken)
    {
        response = Error(id, -32001, "unauthorized");
    }
    else if (!parameters.TryGetProperty("contractVersion", out var version)
        || version.ValueKind != JsonValueKind.Number
        || !version.TryGetInt32(out var suppliedVersion)
        || suppliedVersion != ContractVersion)
    {
        response = Error(id, -32002, "incompatible contract version");
    }
    else if (root.TryGetProperty("method", out var method)
        && method.ValueKind == JsonValueKind.String
        && method.GetString() == "health")
    {
        response = new
        {
            jsonrpc = "2.0",
            id,
            result = new
            {
                contractVersion = ContractVersion,
                status = "ok",
                implementation = "dotnet",
                capabilities = new[] { "health" },
            },
        };
    }
    else
    {
        response = Error(id, -32601, "method not found");
    }

    await writer.WriteLineAsync(JsonSerializer.Serialize(response));
}

static object Error(JsonElement id, int code, string message) => new
{
    jsonrpc = "2.0",
    id,
    error = new { code, message },
};

static async Task<string?> ReadLineLimited(NetworkStream stream)
{
    using var line = new MemoryStream();
    var buffer = new byte[4096];
    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
    while (true)
    {
        var count = await stream.ReadAsync(buffer.AsMemory(), timeout.Token);
        if (count == 0)
        {
            return line.Length == 0 ? null : Encoding.UTF8.GetString(line.ToArray());
        }
        var newline = Array.IndexOf(buffer, (byte)'\n', 0, count);
        var bytesToKeep = newline >= 0 ? newline : count;
        if (line.Length + bytesToKeep > MaxLineBytes)
        {
            return null;
        }
        line.Write(buffer, 0, bytesToKeep);
        if (newline >= 0)
        {
            return Encoding.UTF8.GetString(line.ToArray()).TrimEnd('\r');
        }
    }
}
