const path = require('path');
const webpack = require('webpack');

module.exports = {
  entry: './scalene-gui.js',
    mode: 'production',
  output: {
    filename: 'scalene-gui-bundle.js',
    path: path.resolve(__dirname, ''),
    libraryTarget: 'window',
  },
  resolve: {
    fallback: {
      "crypto": require.resolve("crypto-browserify"),
      "stream": require.resolve("stream-browserify"),
      "buffer": require.resolve("buffer"),
      "util": require.resolve("util"),
      "assert": require.resolve("assert"),
      "os": require.resolve("os-browserify/browser"),
      "http": require.resolve("stream-http"),
      "https": require.resolve("https-browserify"),
      "url": require.resolve("url/"),
      "zlib": require.resolve("browserify-zlib"),
      "path": require.resolve("path-browserify"),
      "fs": false,
    },
  },
  plugins: [
    new webpack.ProvidePlugin({
      process: 'process/browser',
    }),
  ],
  optimization: {
    minimize: true,            // Enable minimization
    usedExports: false,         // Disable tree shaking
    sideEffects: false,         // Include all files, assuming they have side effects
    concatenateModules: false,  // Disable module concatenation (scope hoisting)
    innerGraph: false,          // Disable inner graph analysis
  },
};
