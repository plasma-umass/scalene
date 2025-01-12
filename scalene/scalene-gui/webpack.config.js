const path = require('path');
const webpack = require('webpack');
const TerserPlugin = require('terser-webpack-plugin');

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
      crypto: require.resolve('crypto-browserify'),
      stream: require.resolve('stream-browserify'),
      buffer: require.resolve('buffer'),
      util: require.resolve('util'),
      assert: require.resolve('assert'),
      os: require.resolve('os-browserify/browser'),
      http: require.resolve('stream-http'),
      https: require.resolve('https-browserify'),
      url: require.resolve('url/'),
      zlib: require.resolve('browserify-zlib'),
      path: require.resolve('path-browserify'),
      fs: false,
    },
  },
  plugins: [
    new webpack.ProvidePlugin({
      process: 'process/browser',
    }),
    new webpack.DefinePlugin({
      'process.env.LANG': JSON.stringify('en_US.UTF-8'),
    }),
  ],
  optimization: {
    minimize: true,
    minimizer: [
      new TerserPlugin({
        terserOptions: {
          output: {
            ascii_only: true, // Escape non-ASCII characters
          },
        },
      }),
    ],
    usedExports: false,
    sideEffects: false,
    concatenateModules: false,
    innerGraph: false,
  },
  devtool: 'source-map', // Enable debugging via source maps
};
