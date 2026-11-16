const { proxyConfig, proxyTargets } = require('./proxy-targets.cjs');

module.exports = proxyConfig(proxyTargets());
