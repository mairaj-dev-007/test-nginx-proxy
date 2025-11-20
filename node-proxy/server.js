const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = process.env.PORT || 8080;

// Parse environment variables
const UPSTREAM_SERVERS = JSON.parse(
  process.env.UPSTREAM_SERVERS || '{"litellm": "http://litellm:4000"}'
);
const SERVER_CONFIG = JSON.parse(process.env.SERVER_CONFIG || '{}');
const DEFAULT_UPSTREAM = process.env.DEFAULT_UPSTREAM || 'litellm';

// Get client IP helper
const getClientIp = (req) => {
  return req.headers['x-forwarded-for']?.split(',')[0]?.trim() ||
         req.headers['x-real-ip'] ||
         req.connection.remoteAddress ||
         req.socket.remoteAddress ||
         req.ip;
};

// Proxy all requests
app.use('/', (req, res, next) => {
  const clientIp = getClientIp(req);
  const host = req.hostname;
  let targetUpstream;

  // If no server config, use default upstream
  if (Object.keys(SERVER_CONFIG).length === 0) {
    targetUpstream = UPSTREAM_SERVERS[DEFAULT_UPSTREAM] || Object.values(UPSTREAM_SERVERS)[0];
  } else {
    // Check if the domain/host is configured
    if (SERVER_CONFIG[host]) {
      const config = SERVER_CONFIG[host];

      // Check IP whitelist if configured
      if (config.allowed_ips && config.allowed_ips.length > 0) {
        if (!config.allowed_ips.includes(clientIp)) {
          return res.status(403).send(`403 Forbidden: IP ${clientIp} not allowed for ${host}`);
        }
      }

      // Get upstream server
      const upstreamName = config.upstream || DEFAULT_UPSTREAM;
      if (!UPSTREAM_SERVERS[upstreamName]) {
        return res.status(502).send(`502 Bad Gateway: Upstream '${upstreamName}' not configured`);
      }

      targetUpstream = UPSTREAM_SERVERS[upstreamName];
    } else {
      // Domain not configured, deny or use default based on config
      if (Object.keys(SERVER_CONFIG).length > 0) {
        return res.status(404).send(`404 Not Found: Host ${host} not configured`);
      }
      targetUpstream = UPSTREAM_SERVERS[DEFAULT_UPSTREAM] || Object.values(UPSTREAM_SERVERS)[0];
    }
  }

  // Create proxy middleware for this request
  const proxy = createProxyMiddleware({
    target: targetUpstream,
    changeOrigin: true,
    ws: true,
    logLevel: 'silent',
    onError: (err, req, res) => {
      console.error('Proxy error:', err.message);
      res.status(502).send(`Bad Gateway: ${err.message}`);
    }
  });

  proxy(req, res, next);
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Node.js Reverse Proxy running on http://0.0.0.0:${PORT}`);
  console.log('Upstream servers:', UPSTREAM_SERVERS);
  console.log('Server config:', SERVER_CONFIG);
  console.log('Default upstream:', DEFAULT_UPSTREAM);
});

