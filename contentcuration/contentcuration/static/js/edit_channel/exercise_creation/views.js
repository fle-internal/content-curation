var Backbone = require("backbone");
var _ = require("underscore");
var ExerciseModels = require("./models");
var $ = require("jquery");
var Quill = require("quilljs");
var Dropzone = require("dropzone");
var get_cookie = require("utils/get_cookie");
var UndoManager = require("backbone-undo");
var JSZip = require("jszip");
var fileSaver = require("browser-filesaver");
var JSZipUtils = require("jszip-utils");

require("../../less/exercises.less");
require("quilljs/dist/quill.snow.css");
require("dropzone/dist/dropzone.css");

var ExerciseListView = Backbone.View.extend({

    initialize: function() {
        this.render();
        this.listenTo(this.collection, "sync", this.render);
        this.listenTo(this.collection, "remove", this.render);
    },

    events: {
        "click .create": "add_exercise",
        "click .delete": "delete_exercise"
    },

    template: require("./hbtemplates/exercise_list.handlebars"),

    render: function (){
        this.$el.html(this.template({exercise_list: this.collection.toJSON()}))
    },

    add_exercise: function() {
        this.collection.create();
    },

    delete_exercise: function(ev) {
        var id = ev.currentTarget.value;
        var model = this.collection.get(id);
        model.destroy();
        return false;
    }
});

var FileUploadView = Backbone.View.extend({

    initialize: function(options) {
        _.bindAll(this, "file_uploaded");
        this.callback = options.callback;
        this.modal = options.modal;
        this.render();
    },

    template: require("./hbtemplates/file_upload.handlebars"),

    modal_template: require("./hbtemplates/file_upload_modal.handlebars"),

    render: function() {

        if (this.modal) {
            this.$el.html(this.modal_template());
            this.$(".modal-body").append(this.template());
            $("body").append(this.el);
            this.$(".modal").modal({show: true});
            this.$(".modal").on("hide.bs.modal", this.close);
        } else {
            this.$el.html(this.template());
        }

        // TODO parameterize to allow different file uploads depending on initialization.
        this.dropzone = new Dropzone(this.$("#dropzone").get(0), {maxFiles: 1, clickable: ["#dropzone", ".fileinput-button"], acceptedFiles: "image/*", url: window.Urls.file_upload(), headers: {"X-CSRFToken": get_cookie("csrftoken")}});
        this.dropzone.on("success", this.file_uploaded);

    },

    file_uploaded: function(file) {
        this.callback(JSON.parse(file.xhr.response).filename);
        this.close();
    },

    close: function() {
        if (this.modal) {
            this.$(".modal").modal('hide');
        }
        this.remove();
    }
});

var EditorView = Backbone.View.extend({

    tagName: "div",

    initialize: function(options) {
        _.bindAll(this, "return_markdown", "add_image", "deactivate_editor", "activate_editor", "save_and_close", "save", "render");
        this.edit_key = options.edit_key;
        this.editing = false;
        this.render();
        this.listenTo(this.model, "change:" + this.edit_key, this.render);
    },

    events: {
        "click .ql-image": "add_image_popup"
    },

    add_image_popup: function() {
        var view = new FileUploadView({callback: this.add_image, modal: true});
    },

    add_image: function(filename) {
        this.editor.insertEmbed(this.editor.getSelection() !== null ? this.editor.getSelection().start : this.editor.getLength(), "image", "/media/" + filename);
        this.save();
    },

    edit_template: require("./hbtemplates/editor.handlebars"),

    view_template: require("./hbtemplates/editor_view.handlebars"),

    render: function() {
        if (this.editing) {
            if (!this.setting_model) {
                /*
                * (rtibbles)
                * The view rerenders on model change. But, the save method below modifies the exact attribute that it is listening to.
                * If we don't stop the rerender, we needlessly reparse the markdown to HTML into the editor.
                * This led to some weird behaviour (due to race conditions) during manual testing, so I stopped it.
                *
                * The only other alternative would be to do the set in the save method with {silent: true} as an option,
                * but other behaviour relies on listening to the model's change events.
                */
                this.render_editor();
            }
        } else {
            this.render_content();
        }
        this.setting_model = false;
    },

    render_content: function() {
        this.$el.html(this.view_template({content: this.model.get(this.edit_key)}));
    },

    render_editor: function() {
        this.editor.setHTML(this.view_template({content: this.model.get(this.edit_key)}));
    },

    activate_editor: function() {
        this.$el.html(this.edit_template());
        this.editor = new Quill(this.$(".editor")[0], {
            modules: {
                'toolbar': { container: this.$('#toolbar')[0] }
            },
            theme: 'snow',
            styles: {
                'body': {
                  'background-color': "white",
                  'border': '1px #66afe9 solid',
                  'border-radius': "4px",
                  "box-shadow": "inset 0 1px 1px rgba(0,0,0,.075),0 0 8px rgba(102,175,233,.6)"
                }
            }
        });
        this.render_editor();
        this.editor.on("text-change", _.debounce(this.save, 500));
        this.editing = true;
        this.editor.focus();
    },

    deactivate_editor: function() {
        delete this.editor;
        this.editing = false;
        this.render();
    },

    toggle_editor: function() {
        if (this.editor) {
            this.deactivate_editor();
        } else {
            this.activate_editor();
        }
    },

    save: function(delta, source) {
        /*
        * This method can be triggered by a change event firing on the QuillJS
        * instance that we are using. As such, it supplies arguments delta and source.
        * Delta describes the change in the Editor instance, while source defines whether
        * those changes were user initiated or made via the API.
        * Doing this check prevents us from continually rerendering when a non-user source
        * modifies the contents of the editor (i.e. our own code).
        */
        if (typeof source !== "undefined" && source !== "user") {
            return;
        }
        this.setting_model = true;
        this.model.set(this.edit_key, this.return_markdown());
    },

    save_and_close: function() {
        this.save();
        this.deactivate_editor();
    },

    return_html: function() {
        return this.editor.getHTML();
    },

    return_markdown: function() {
        var contents = this.editor.getContents();
        var outputs = [];
        for (var i = 0; i < contents.ops.length; i++) {
            var insert = contents.ops[i].insert;
            var attributes = contents.ops[i].attributes;
            if (typeof attributes !== "undefined") {
                _.each(attributes, function(value, key) {
                    switch (key) {
                        case "bold":
                            if (value) {
                                insert = "**" + insert + "**";
                            }
                            break;
                        case "italic":
                            if (value) {
                                insert = "*" + insert + "*";
                            }
                            break;
                        case "image":
                            if (value && insert === 1) {
                                insert = "![](" + value + ")";
                            }
                            break;
                    }
                })
            }
            outputs.push(insert);
        }
        return outputs.join("");
    }
});

/**
 * Replace local 'media' urls with 'web+local://'.
 * @param {string} Markdown containing image URLs.
 * Should take a string of markdown like:
 * "something![foo](/media/bar/baz)otherthings"
 * and turn it into:
 * "something![foo](web+local://bar/baz)otherthings"
 */
var set_image_urls_for_export = function(text) {
    return text.replace(/(\!\[[^\]]*\]\()(\/media\/)([^\)]*\))/g, "$1web+local://$3");
};


/**
 * Return all image URLs from Markdown.
 * @param {string} Markdown containing image URLs.
 * Should take a string of markdown like:
 * "something![foo](/media/bar/baz.png)otherthings something![foo](/media/bar/foo.jpg)otherthings"
 * and return:
 * ["/media/bar/baz.png", "/media/bar/foo.jpg"]
 */
var return_image_urls_for_export = function(text) {
    var match, output = [];
    var Re = /\!\[[^\]]*\]\((\/media\/[^\)]*)\)/g;
    while (match = Re.exec(text)) {
        output.push(match[1]);
    }
    return output;
};

/**
 * Return all image URLs from an assessment item.
 * @param {object} Backbone Model.
 * Should take a model with a "question" attribute that is a string of Markdown,
 * and an "answers" attribute that is a Backbone Collection, with each 
 * model having an "answer" attribute that is also a string of markdown
 * and return all the image URLs embedded inside all the Markdown texts.
 */
var return_all_assessment_item_image_urls = function(model) {
    var output = return_image_urls_for_export(model.get("question"));
    var output = model.get("answers").reduce(function(memo, model) {
        memo = memo.concat(return_image_urls_for_export(model.get("answer")));
        return memo;
    }, output);

    output = _.map(output, function(item) {
        return {
            name: item.replace(/\/media\//g, ""),
            path: item
        }
    });
    return output;
}

/**
 * Return JSON object in Perseus format.
 * @param {object} Backbone Model - AssessmentItem.
 */
var convert_assessment_item_to_perseus = function(model) {
    var multiplechoice_template = require("./hbtemplates/assessment_item_multiple.handlebars");
    var freeresponse_template = require("./hbtemplates/assessment_item_free.handlebars");
    var output = "";
    switch (model.get("type")) {
        case "freeresponse":
            output = freeresponse_template(model.attributes);
            break;
        case "multiplechoice":
            output = multiplechoice_template({
                question: set_image_urls_for_export(model.get("question")),
                randomize: true,
                multipleSelect: (model.get("answers").reduce(function(memo, model) {
                    if (model.get("correct")) {
                        memo += 1;
                    }
                    return memo;
                    }, 0) || 0) > 1,
                answer: model.get("answers").toJSON()
            });
            break;
    }
    return $.parseJSON(output);
};


var slugify = function(text) {
    // https://gist.github.com/mathewbyrne/1280286
    return text.toString().toLowerCase()
        .replace(/\s+/g, '-')           // Replace spaces with -
        .replace(/[^\w\-]+/g, '')       // Remove all non-word chars
        .replace(/\-\-+/g, '-')         // Replace multiple - with single -
        .replace(/^-+/, '')             // Trim - from start of text
        .replace(/-+$/, '');            // Trim - from end of text
    }

var exerciseSaveDispatcher = _.clone(Backbone.Events);

var ExerciseView = Backbone.View.extend({
    
    initialize: function() {
        _.bindAll(this, "add_all_assessment_items", "render", "save");
        this.listenTo(this.collection, "remove", this.render);
        this.listenTo(exerciseSaveDispatcher, "save", this.save);
        this.render();
    },

    events: {
        "click .multiplechoice": "multiplechoice",
        "click .truefalse": "truefalse",
        "click .freeresponse": "freeresponse",
        "change #title": "set_title",
        "change #description": "set_description",
        "click .save": "save",
        "click .download": "download"
    },

    download: function() {
        var self = this;
        var zip = new JSZip();
        zip.file("exercise.json", JSON.stringify({
            title: this.model.get("title"),
            description: this.model.get("description"),
            all_assessment_items: this.collection.map(function(model){return model.get("id");})
        }));
        zip.file("assessment_items.json", JSON.stringify(this.collection.map(function(model){
            return convert_assessment_item_to_perseus(model);
        })));
        var all_image_urls = this.collection.reduce(function(memo, model){
            memo = memo.concat(return_all_assessment_item_image_urls(model));
            return memo;
        }, []);

        var downloads = 0;

        if (all_image_urls.length > 0) {

            _.each(all_image_urls, function(item) {
                JSZipUtils.getBinaryContent(item.path, function(err, data) {
                    if (err) {
                        throw err
                    }
                    zip.file(item.name, data, {binary: true});
                    downloads += 1;
                    console.log(downloads);
                    if (downloads === all_image_urls.length) {
                        var blob = zip.generate({type:"blob"});

                        fileSaver.saveAs(blob, slugify(self.model.get("title")) + ".exercise");
                    }
                });
        });
        } else {
            var blob = zip.generate({type:"blob"});

            fileSaver.saveAs(blob, slugify(self.model.get("title")) + ".exercise");
        }

    },

    save: function() {
        this.model.save();
        this.collection.save();
    },

    set_title: function(){
        this.model.set("title", this.$("#title").prop("value"));
    },

    set_description: function(){
        this.model.set("description", this.$("#description").prop("value"));
    },

    template: require("./hbtemplates/exercise_edit.handlebars"),

    render: function() {
        this.$el.html(this.template(this.model.attributes));
        _.defer(this.add_all_assessment_items);
    },

    add_all_assessment_items: function() {
        for (var i = 0; i < this.collection.length; i++){
            this.add_assessment_item_view(this.collection.at(i), i);
        }
    },

    add_assessment_item_view: function(model, i) {
        var view = new AssessmentItemView({model: model, number: i + 1});
        this.$("#accordion").append(view.el);
    },

    add_assessment_item: function(type, data) {
        var model_data = {
            type: type,
            exercise: this.model.get("id")
        };
        if (data) {
            model_data = _.extend(model_data, data);
        }
        var self = this;
        this.collection.create(model_data,{
            success: function (model){
                self.add_assessment_item_view(model, self.collection.indexOf(model));
            }
        });

    },

    multiplechoice: function() {
        this.add_assessment_item("multiplechoice");
    },

    truefalse: function() {
        this.add_assessment_item("multiplechoice", {
            answers: "[{\"answer\": \"True\", \"correct\": true}, {\"answer\": \"False\", \"correct\": false}]"
        });
    },

    freeresponse: function() {
        this.add_assessment_item("freeresponse");
    }
});


var AssessmentItemAnswerView = Backbone.View.extend({

    initialize: function(options) {
        _.bindAll(this, "render", "set_editor");
        this.open = options.open || false;
        this.render();
    },

    template: require("./hbtemplates/assessment_item_answer.handlebars"),
    closed_toolbar_template: require("./hbtemplates/assessment_item_answer_toolbar_closed.handlebars"),
    open_toolbar_template: require("./hbtemplates/assessment_item_answer_toolbar_open.handlebars"),

    events: {
        "click .edit": "toggle_editor",
        "click .delete": "delete",
        "change .correct": "toggle_correct"
    },

    render: function() {
        this.$el.html(this.template(this.model.attributes));
        if (!this.editor_view) {
            this.editor_view = new EditorView({model: this.model, edit_key: "answer", el: this.$(".answer")});
        } else {
            this.$(".answer").append(this.editor_view.el);
        }
        _.defer(this.set_editor);
    },

    toggle_editor: function() {
        this.open = !this.open;
        this.set_editor(true);
    },

    set_editor: function(save) {
        if (this.open) {
            this.set_toolbar_open();
            this.editor_view.activate_editor();
        } else {
            this.set_toolbar_closed();
            this.editor_view.deactivate_editor();
            if (save) {
                exerciseSaveDispatcher.trigger("save");
            }
        }
    },

    toggle_correct: function() {
        this.model.set("correct", this.$(".correct").prop("checked"));
    },

    set_toolbar_open: function() {
        this.$(".answer-toolbar").html(this.open_toolbar_template());
    },

    set_toolbar_closed: function() {
        this.$(".answer-toolbar").html(this.closed_toolbar_template());
    },

    delete: function() {
        this.model.destroy();
        exerciseSaveDispatcher.trigger("save");
        this.remove();
    }

});


var AssessmentItemAnswerListView = Backbone.View.extend({

    template: require("./hbtemplates/assessment_item_answer_list.handlebars"),

    initialize: function() {
        _.bindAll(this, "render");
        this.render();
        this.listenTo(this.collection, "add", this.add_answer_view);
        this.listenTo(this.collection, "remove", this.render);
    },

    events: {
        "click .addanswer": "add_answer"
    },

    render: function() {
        this.$el.html(this.template());
        for (var i = 0; i < this.collection.length; i++) {
            this.add_answer_view(this.collection.at(i));
        }
    },

    add_answer: function() {
        this.collection.add({answer: "", correct: false});
    },

    add_answer_view: function(model, open) {
        open = open ? true : false;
        var view = new AssessmentItemAnswerView({model: model, open: open});
        this.$(".list-group").append(view.el);
    }

});


var AssessmentItemView = Backbone.View.extend({
    
    initialize: function(options) {
        _.bindAll(this, "set_toolbar_open", "set_toolbar_closed", "save", "set_undo_redo_listener", "unset_undo_redo_listener", "toggle_undo_redo");
        this.number = options.number;
        this.undo_manager = new UndoManager({
            track: true,
            register: [this.model, this.model.get("answers")]
        });
        this.toggle_undo_redo();
        this.render();
    },

    template: require("./hbtemplates/assessment_item_edit.handlebars"),
    closed_toolbar_template: require("./hbtemplates/assessment_item_edit_toolbar_closed.handlebars"),
    open_toolbar_template: require("./hbtemplates/assessment_item_edit_toolbar_open.handlebars"),

    events: {
        "click .cancel": "cancel",
        "click .undo": "undo",
        "click .redo": "redo",
        "click .delete": "delete"
    },

    delete: function() {
        this.model.destroy();
        exerciseSaveDispatcher.trigger("save");
        this.remove();
    },

    save: function() {
        exerciseSaveDispatcher.trigger("save");
        this.set_toolbar_closed();
    },

    cancel: function() {
        this.undo_manager.undoAll();
    },

    undo: function() {
        this.undo_manager.undo();
    },

    redo: function() {
        this.undo_manager.redo();
    },

    toggle_undo_redo: function() {
        var undo = this.undo;
        var redo = this.redo;
        this.undo = this.undo_manager.isAvailable("undo");
        this.redo = this.undo_manager.isAvailable("redo");
        if (undo !== this.undo || redo !== this.redo) {
            this.set_toolbar_open();
        }
    },

    render: function() {
        // Clean up any previous event listeners just to be tidy.
        this.$(".collapse").off("show.bs.collapse");
        this.$(".collapse").off("hidden.bs.collapse");

        this.$el.html(this.template({model: this.model.attributes, number: this.number}));
        this.set_toolbar_closed();
        if (this.model.get("type") === "multiplechoice") {
            if (!this.answer_editor) {
                this.answer_editor = new AssessmentItemAnswerListView({collection: this.model.get("answers")});
            }
            this.$(".answers").append(this.answer_editor.el);
        }
        if (!this.editor_view) {
            this.editor_view = new EditorView({model: this.model, edit_key: "question", el: this.$(".question")});
        } else {
            this.$(".question").append(this.editor_view.el);
        }
        this.$(".collapse").on("show.bs.collapse", this.editor_view.activate_editor);
        this.$(".collapse").on("hidden.bs.collapse", this.editor_view.save_and_close);
        this.$(".collapse").on("show.bs.collapse", this.set_toolbar_open);
        this.$(".collapse").on("hidden.bs.collapse", this.save);
        this.$(".collapse").on("show.bs.collapse", this.set_undo_redo_listener);
        this.$(".collapse").on("hidden.bs.collapse", this.unset_undo_redo_listener);
    },

    set_undo_redo_listener: function() {
        this.listenTo(this.undo_manager.stack, "add", this.toggle_undo_redo);
        this.listenTo(this.undo_manager, "all", this.toggle_undo_redo);
    },

    unset_undo_redo_listener: function() {
        this.stopListening(this.undo_manager.stack);
        this.stopListening(this.undo_manager);
    },

    set_toolbar_open: function() {
        this.$(".toolbar").html(this.open_toolbar_template({model: this.model.attributes, undo: this.undo, redo: this.redo}));
    },

    set_toolbar_closed: function() {
        this.$(".toolbar").html(this.closed_toolbar_template({model: this.model.attributes}));
    }
});

module.exports = {
    ExerciseListView: ExerciseListView,
    ExerciseView: ExerciseView,
    AssessmentItemView: AssessmentItemView
};