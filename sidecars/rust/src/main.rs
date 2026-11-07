use serde_json::{json, Value};
use std::env;
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};

const CONTRACT_VERSION: u64 = 1;
const MAX_LINE_BYTES: usize = 1_048_576;

fn error_response(id: Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})
}

fn dispatch(request: &Value, expected_token: &str) -> Value {
    let id = request.get("id").cloned().unwrap_or(Value::Null);
    if request.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return error_response(id, -32600, "invalid JSON-RPC request");
    }
    let params = match request.get("params").and_then(Value::as_object) {
        Some(value) => value,
        None => return error_response(id, -32600, "params must be an object"),
    };
    if params.get("token").and_then(Value::as_str) != Some(expected_token) {
        return error_response(id, -32001, "unauthorized");
    }
    if params.get("contractVersion").and_then(Value::as_u64) != Some(CONTRACT_VERSION) {
        return error_response(id, -32002, "incompatible contract version");
    }
    match request.get("method").and_then(Value::as_str) {
        Some("health") => json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "contractVersion": CONTRACT_VERSION,
                "status": "ok",
                "implementation": "rust",
                "capabilities": ["health"]
            }
        }),
        _ => error_response(id, -32601, "method not found"),
    }
}

fn handle_client(stream: TcpStream, token: &str) -> std::io::Result<()> {
    stream.set_read_timeout(Some(std::time::Duration::from_secs(2)))?;
    stream.set_write_timeout(Some(std::time::Duration::from_secs(2)))?;
    let reader_stream = stream.try_clone()?;
    let reader = BufReader::new(reader_stream);
    let mut limited_reader = reader.take((MAX_LINE_BYTES + 1) as u64);
    let mut line = String::new();
    let bytes = limited_reader.read_line(&mut line)?;
    if bytes == 0 || bytes > MAX_LINE_BYTES {
        return Ok(());
    }
    let response = match serde_json::from_str::<Value>(&line) {
        Ok(request) => dispatch(&request, token),
        Err(_) => error_response(Value::Null, -32700, "parse error"),
    };
    let mut writer = BufWriter::new(stream);
    serde_json::to_writer(&mut writer, &response)?;
    writer.write_all(b"\n")?;
    writer.flush()
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = env::var("JARVIS_POLYGLOT_TOKEN")?;
    if token.len() < 32 {
        return Err("JARVIS_POLYGLOT_TOKEN must contain at least 32 characters".into());
    }
    let port: u16 = env::var("JARVIS_SIDECAR_PORT")
        .unwrap_or_else(|_| "18761".to_string())
        .parse()?;
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port);
    let listener = TcpListener::bind(address)?;
    eprintln!("jarvis rust sidecar listening on 127.0.0.1:{port} (contract v{CONTRACT_VERSION})");
    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => {
                if let Err(error) = handle_client(stream, &token) {
                    eprintln!("jarvis rust sidecar request failed: {error}");
                }
            }
            Err(error) => eprintln!("jarvis rust sidecar accept failed: {error}"),
        }
    }
    Ok(())
}
