const path = require('path');
const { ModuleFederationPlugin } = require('webpack').container;
const packageConfig = require('./package.json');
const extensionConfig = require('../extension.json');

module.exports = {
  mode: 'production',
  entry: './src/index.tsx',
  output: {
    clean: true,
    filename: '[name].[contenthash].js',
    chunkFilename: '[name].[contenthash].js',
    path: path.resolve(__dirname, 'dist'),
    publicPath: `/api/v1/extensions/${extensionConfig.publisher}/${extensionConfig.name}/`,
  },
  resolve: { extensions: ['.ts', '.tsx', '.js', '.jsx'], alias: { '@': path.resolve(__dirname, 'src') } },
  externalsType: 'window',
  externals: { '@apache-superset/core': 'superset' },
  module: {
    rules: [
      // Base UI ships ESM (.mjs) that imports react/jsx-runtime without an extension; React 17 has no exports map.
      { test: /\.m?js$/, resolve: { fullySpecified: false } },
      { test: /\.tsx?$/, use: { loader: 'ts-loader', options: { transpileOnly: true } }, exclude: /node_modules/ },
      { test: /\.css$/, use: ['style-loader', 'css-loader', 'postcss-loader'] },
    ],
  },
  plugins: [
    new ModuleFederationPlugin({
      name: 'textToBi_supersetSemanticLayer',
      filename: 'remoteEntry.[contenthash].js',
      exposes: { './index': './src/index.tsx' },
      shared: {
        react: { singleton: true, requiredVersion: packageConfig.peerDependencies.react, import: false },
        'react-dom': { singleton: true, requiredVersion: packageConfig.peerDependencies['react-dom'], import: false },
      },
    }),
  ],
};
