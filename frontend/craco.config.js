const path = require("path");
require("dotenv").config();
const config = {
  enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true",
};
let webpackConfig = {
  eslint: {
    enable: false,
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {
      webpackConfig.cache = false;
      webpackConfig.plugins = webpackConfig.plugins.filter(p => {
        const name = p.constructor && p.constructor.name;
        return name !== 'ESLintWebpackPlugin';
      });
      return webpackConfig;
    },
  },
};
module.exports = webpackConfig;
