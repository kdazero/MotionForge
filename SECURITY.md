# Security and deployment scope

MotionForge is a local, single-user authoring tool. Prefer stdio. The optional HTTP transport binds to 127.0.0.1 and does not implement user authentication. It is not designed as an Internet-facing, multi-tenant rendering service.

The server operates on files inside the configured workspace. Choose a dedicated directory containing only the assets and outputs you intend the client to access. Image inspection and artifact-reading tools can return workspace file contents to the connected client. A local model and a hosted model may have different data handling policies.

Do not expose the local HTTP port directly to the Internet. Do not use untrusted shared writable workspaces. Limits reduce resource usage but are not a complete sandbox for hostile inputs.

If GitHub private vulnerability reporting is enabled, use the repository Security tab. Otherwise open an issue asking for a private contact route without posting exploit details, private files, credentials or sensitive logs. No dedicated security response service is promised for this preview release.
