var path = require('path');

var ExtractTextPlugin = require('extract-text-webpack-plugin');
var ManifestRevisionPlugin = require('manifest-revision-webpack-plugin');

const externalCSS = new ExtractTextPlugin('[name].[contenthash].css');

module.exports = {
  entry: {
    main: ['./app/static/js/main.js'],
  },
  output: {
    path: path.resolve(__dirname, 'app/static/gen'),
    filename: '[name].[chunkhash].js',
    chunkFilename: '[id].[chunkhash].js',
    publicPath: '/static/gen/'
  },
  module: {
    rules: [
      {
        test: /\.js$/,
        exclude: /(node_modules|bower_components|ext)/,
        use: {
          loader: 'babel-loader',
          options: {
            plugins: ['transform-es2015-modules-commonjs']
          }
        }
      },
      {
        test: /\.css$/,
        loader: externalCSS.extract({ fallback: 'style-loader', use: 'css-loader' })
      },
      {
        test: /\.svg$/,
        exclude: [/sprite\.svg/],
        loader: 'svg-inline-loader'
      },
    ],
  },
  plugins: [
    externalCSS,
    new ManifestRevisionPlugin('./app/manifest.json', {
      rootAssetPath: './app/static/gen',
      ignorePaths: ['/static']
    })
  ]
};