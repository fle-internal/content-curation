const esLintConfig = require('kolibri-tools/.eslintrc');
const webpack = require('./webpack.config.js')();

esLintConfig.globals = {
  $: false,
  _: false,
  MathQuill: false,
  HandlebarsIntl: false,
  MathJax: false,
  Raven: false,
  jest: false,
};
esLintConfig.settings['import/resolver'].alias = {
  map: Object.entries(webpack.resolve.alias),
  extensions: ['.vue', '.less', '.js', '.handlebars'],
};
// Vuetify's helper attributes use hyphens and they would
// not be recognized if auto-formatted to camel case
esLintConfig.rules['vue/attribute-hyphenation'] = 0;

module.exports = esLintConfig;
