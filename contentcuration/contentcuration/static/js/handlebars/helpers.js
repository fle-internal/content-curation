var Handlebars = require("hbsfy/runtime");
var marked = require("marked");
var stringHelper = require("edit_channel/utils/string_helper");

marked.setOptions({
  renderer: new marked.Renderer(),
  gfm: true,
  tables: false,
  breaks: true,
  pedantic: false,
  sanitize: false,
  smartLists: false,
  smartypants: false
});

// A little bit of magic to let us use Django JS Reverse directly from inside a Handlebars template
// Simply pass any arguments that you might otherwise use in order
Handlebars.registerHelper('url', function(url_name) {
    var ref;
    // Make check more robust so that undefined urls also return empty string
    if (((ref = window.Urls) !== undefined ? ref[url_name] : void 0) !== undefined) {
        var args = Array.prototype.slice.call(arguments, 1, -1);
        return window.Urls[url_name].apply(window.Urls, args);
    } else {
        if (!window.Urls) {
            console.warn("Django Reverse JS not loaded");
        } else if (!window.Urls[url_name]) {
            console.warn("Url name invalid");
        }
        return "";
    }
});

// A little bit of magic to let us render markdown into a Handlebars template
Handlebars.registerHelper('markdown', function(markdown) {
    if (markdown) {
        markdown = markdown.toString().replace(/\n(\n)/g, "$1<br />");
        return marked(markdown);
    } else {
        return "";
    }
});

// Replace newline characters with \n
Handlebars.registerHelper('parse_newlines', function(text) {
  if (text) {
    text = text.replace(/\n/g, "\\n");
  }
  return text;
});

// Convert text to all caps
Handlebars.registerHelper('to_upper_case', function(text){
  return text.toUpperCase();
});

Handlebars.registerHelper('check_is_topic', function(text){
  return text === "topic";
});

Handlebars.registerHelper('get_filename', function(text){
  return text.split(".")[-1];
});

Handlebars.registerHelper('format_file_size', function(text){
  return stringHelper.format_size(text);
});

Handlebars.registerHelper('format_count', function(text, count){
  if(Number(count) === 1){
    return count + " " + text;
  }
  return count + " " + text + "s";
});
Handlebars.registerHelper('get_icon', function(kind){
  switch (kind){
      case "topic":
          return "glyphicon glyphicon-folder-close";
      case "video":
          return "glyphicon glyphicon-film";
      case "audio":
          return "glyphicon glyphicon-headphones";
      case "image":
          return "glyphicon glyphicon-picture";
      case "exercise":
          return "glyphicon glyphicon-star";
      case "document":
          return "glyphicon glyphicon-file";
      case "html5":
          return "glyphicon glyphicon-certificate";
      default:
          return "glyphicon glyphicon-exclamation-sign";
  }
});

Handlebars.registerHelper('format_question_type', function(type){
  switch (type){
      case "multiple_selection":
          return "Multiple Selection";
      case "single_selection":
          return "Single Selection";
      case "input_question":
          return "Input Answer";
      case "perseus_question":
          return "Perseus Question";
      default:
          return "Unknown Question Type";
  }
});

Handlebars.registerHelper('substring', function(text, chars){
  return text.substring(0, chars);
});

Handlebars.registerHelper('question_default_text', function(type){
  return type === "perseus_question"? "Perseus Question" : "No text provided";
});
