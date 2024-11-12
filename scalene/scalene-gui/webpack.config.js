const path = require('path');
const webpack = require('webpack'); // Add this line

module.exports = {
  entry: './scalene-gui.js',
    mode: 'production', // 'development',
//    devtool: false,
  output: {
    filename: 'scalene-gui-bundle.js',
    path: path.resolve(__dirname, ''),
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
      "fs": false, // fs module is not available in the browser
    },
  },
  plugins: [
    // Necessary to define process.env
    new webpack.ProvidePlugin({
      process: 'process/browser',
    }),
  ],
};
