<template>

  <div
    style="position: relative;"
    class="wrapper"
    :class="{ highlight, uploading: Boolean(uploadingChecksum) }"
    @dragenter="highlight = true"
    @dragover="highlight = true"
    @dragleave="highlight = false"
    @drop="highlight = false"
  >
    <div
      ref="editor"
      class="editor"
    ></div>

    <FormulasMenu
      v-if="formulasMenu.isOpen"
      v-model="formulasMenu.formula"
      v-click-outside="onClick"
      class="formulas-menu"
      :anchorArrowSide="formulasMenu.anchorArrowSide"
      :mathQuill="mathQuill"
      style="position:absolute"
      :style="formulasMenu.style"
      @insert="onFormulasMenuInsert"
      @cancel="onFormulasMenuCancel"
    />
    <ImagesMenu
      v-if="imagesMenu.isOpen"
      ref="imagesMenu"
      v-click-outside="onClick"
      class="images-menu"
      :anchorArrowSide="imagesMenu.anchorArrowSide"
      style="position:absolute"
      :style="imagesMenu.style"
      :src="imagesMenu.src"
      :alt="imagesMenu.alt"
      :handleFileUpload="handleFileUpload"
      :getFileUpload="getFileUpload"
      :imagePreset="imagePreset"
      @insert="insertImageToEditor"
      @cancel="onImagesMenuCancel"
    />
  </div>

</template>

<script>

  /**
   * * * * * * * * * * * * * * * * * * *
   * See docs/markdown_editor_viewer.md
   * * * * * * * * * * * * * * * * * * *
   */

  import '../mathquill/mathquill.js';
  import 'codemirror/lib/codemirror.css';
  import '@toast-ui/editor/dist/toastui-editor.css';
  import * as Showdown from 'showdown';

  import Editor from '@toast-ui/editor';
  import debounce from 'lodash/debounce';

  import imageUpload, { paramsToImageFieldHTML } from '../plugins/image-upload';
  import formulas from '../plugins/formulas';
  import minimize from '../plugins/minimize';
  import formulaHtmlToMd from '../plugins/formulas/formula-html-to-md';
  import formulaMdToHtml from '../plugins/formulas/formula-md-to-html';
  import imagesHtmlToMd from '../plugins/image-upload/image-html-to-md';
  import imagesMdToHtml from '../plugins/image-upload/image-md-to-html';

  import { CLASS_MATH_FIELD_ACTIVE } from '../constants';
  import { registerMarkdownFormulaField } from '../plugins/formulas/MarkdownFormulaField';
  import { registerMarkdownImageField } from '../plugins/image-upload/MarkdownImageField';
  import { clearNodeFormat, getExtensionMenuPosition } from './utils';
  import keyHandlers from './keyHandlers';
  import FormulasMenu from './FormulasMenu/FormulasMenu';
  import ImagesMenu from './ImagesMenu/ImagesMenu';
  import ClickOutside from 'shared/directives/click-outside';

  registerMarkdownFormulaField();
  registerMarkdownImageField();

  const wrapWithSpaces = html => `&nbsp;${html}&nbsp;`;

  const AnalyticsActionMap = {
    Bold: 'Bold',
    Italic: 'Italicize',
  };

  export default {
    name: 'MarkdownEditor',
    components: {
      FormulasMenu,
      ImagesMenu,
    },
    directives: {
      ClickOutside,
    },
    model: {
      prop: 'markdown',
      event: 'update',
    },
    props: {
      markdown: {
        type: String,
      },
      // Inject function to handle file uploads
      handleFileUpload: {
        type: Function,
      },
      // Inject function to get file upload object
      getFileUpload: {
        type: Function,
      },
      imagePreset: {
        type: String,
      },
      analyticsLabel: {
        type: String,
        default: null,
      },
    },
    data() {
      return {
        editor: null,
        highlight: false,
        formulasMenu: {
          isOpen: false,
          formula: '',
          anchorArrowSide: null,
          style: {
            top: 'initial',
            left: 'initial',
            right: 'initial',
          },
        },
        imagesMenu: {
          isOpen: false,
          anchorArrowSide: null,
          src: '',
          alt: '',
          style: {
            top: 'initial',
            left: 'initial',
            right: 'initial',
          },
        },
        activeImageField: null,
        uploadingChecksum: '',
        mathQuill: null,
        keyDownEventListener: null,
        clickEventListener: null,
        editImageEventListener: null,
      };
    },
    watch: {
      markdown(newMd, previousMd) {
        if (newMd !== previousMd && newMd !== this.editor.getMarkdown()) {
          this.editor.setMarkdown(newMd);
          this.updateCustomNodeSpacers();
          this.initImageFields();
        }
      },
    },
    mounted() {
      this.mathQuill = MathQuill.getInterface(2);

      // This is currently the only way of inheriting and adjusting
      // default TUI's convertor methods
      // see https://github.com/nhn/tui.editor/issues/615
      const tmpEditor = new Editor({
        el: this.$refs.editor,
      });
      const showdown = new Showdown.Converter();
      const Convertor = tmpEditor.convertor.constructor;
      class CustomConvertor extends Convertor {
        toMarkdown(content) {
          content = showdown.makeMarkdown(content);
          content = imagesHtmlToMd(content);
          content = formulaHtmlToMd(content);
          content = content.replaceAll('&nbsp;', ' ');

          // TUI.editor sprinkles in extra `<br>` tags that Kolibri renders literally
          content = content.replaceAll('<br>', '');
          return content;
        }
        toHTML(content) {
          // Kolibri and showdown assume double newlines for a single line break,
          // wheras TUI.editor prefers single newline characters.
          content = content.replaceAll('\n\n', '\n');
          content = super.toHTML(content);
          return content;
        }
      }
      tmpEditor.remove();

      const createBoldButton = () => {
        {
          const button = document.createElement('button');
          button.className = 'tui-bold tui-toolbar-icons';
          return button;
        }
      };
      const createItalicButton = () => {
        {
          const button = document.createElement('button');
          button.className = 'tui-italic tui-toolbar-icons';
          return button;
        }
      };
      const options = {
        el: this.$refs.editor,
        minHeight: '240px',
        height: 'auto',
        initialValue: this.markdown,
        initialEditType: 'wysiwyg',
        usageStatistics: false,
        toolbarItems: [
          {
            type: 'button',
            options: {
              el: createBoldButton(),
              command: 'Bold',
              tooltip: this.$tr('bold'),
            },
          },
          {
            type: 'button',
            options: {
              el: createItalicButton(),
              command: 'Italic',
              tooltip: this.$tr('italic'),
            },
          },
        ],
        hideModeSwitch: true,
        plugins: [
          [
            imageUpload,
            {
              onImageDrop: this.onImageDrop,
              onImageUploadToolbarBtnClick: this.onImageUploadToolbarBtnClick,
              toolbarBtnTooltip: this.$tr('image'),
            },
          ],
          [
            formulas,
            {
              onFormulasToolbarBtnClick: this.onFormulasToolbarBtnClick,
              toolbarBtnTooltip: this.$tr('formulas'),
            },
          ],
          [
            minimize,
            {
              onMinimizeToolbarBtnClick: this.onMinimizeToolbarBtnClick,
              toolbarBtnTooltip: this.$tr('minimize'),
            },
          ],
        ],
        customConvertor: CustomConvertor,
        // https://github.com/nhn/tui.editor/blob/master/apps/editor/docs/custom-html-renderer.md
        customHTMLRenderer: {
          text(node) {
            let content = formulaMdToHtml(node.literal);
            content = imagesMdToHtml(content);
            return {
              type: 'html',
              content,
            };
          },
        },
      };

      this.editor = new Editor(options);

      this.editor.focus();

      this.editor.on('change', () => {
        this.$emit('update', this.editor.getMarkdown());
      });

      // Track analytics events for some commands
      this.editor.on('command', command => {
        const action = AnalyticsActionMap[command];
        if (action) {
          this.trackAnalyticsEvent(action);
          // Some inconsistencies with these events in GA
          this.trackAnalyticsEvent('Click', command);
        }
      });

      this.initMathFields();
      this.initImageFields();

      this.editor.getSquire().addEventListener('willPaste', this.onPaste);
      this.keyDownEventListener = this.$el.addEventListener('keydown', this.onKeyDown, true);
      this.clickEventListener = this.$el.addEventListener('click', this.onClick);
      this.editImageEventListener = this.$el.addEventListener('editImage', this.handleEditImage);

      // Make sure all custom nodes have spacers around them.
      // Note: this is debounced because it's called every keystroke
      const editorEl = this.$refs.editor;
      this.updateCustomNodeSpacers = debounce(() => {
        editorEl.querySelectorAll('span[is]').forEach(el => {
          el.editing = true;
          const hasLeftwardSpace = el => {
            return (
              el.previousSibling &&
              el.previousSibling.textContent &&
              /\s$/.test(el.previousSibling.textContent)
            );
          };
          const hasRightwardSpace = el => {
            return (
              el.nextSibling && el.nextSibling.textContent && /^\s/.test(el.nextSibling.textContent)
            );
          };
          if (!hasLeftwardSpace(el)) {
            el.insertAdjacentText('beforebegin', '\xa0');
          }
          if (!hasRightwardSpace(el)) {
            el.insertAdjacentText('afterend', '\xa0');
          }
        });
      }, 150);

      this.updateCustomNodeSpacers();
    },
    activated() {
      this.editor.focus();
    },
    beforeDestroy() {
      this.editor.getSquire().removeEventListener('willPaste', this.onPaste);
      this.$el.removeEventListener(this.keyDownEventListener, this.onKeyDown, true);
      this.$el.removeEventListener(this.clickEventListener, this.onClick);
      this.$el.removeEventListener(this.editImageEventListener, this.handleEditImage);
    },
    methods: {
      /**
       * Handle Squire keydown events - TUI WYSIWYG editor is built
       * on top of Squire (https://github.com/neilj/Squire)
       * and provides its instance including API methods
       *
       * TUI's `addKeyEventHandler` is not sufficient because they
       * internally override some of the actions that need to be
       * customized from here => needs to be set on Squire level
       * Modifying default Squire key events is not documented but there's
       * a recommended solution here https://github.com/neilj/Squire/issues/107
       */
      onKeyDown(event) {
        const squire = this.editor.getSquire();

        // Apply squire selection workarounds
        this.fixSquireSelectionOnKeyDown(event);

        if (event.key in keyHandlers) {
          keyHandlers[event.key](squire);
        }

        // ESC should close menus if any are open
        // or close the editor if none are open
        if (event.key === 'Escape') {
          event.stopImmediatePropagation();
          if (this.formulasMenu.isOpen) {
            this.resetFormulasMenu();
          } else if (this.imagesMenu.isOpen) {
            this.resetImagesMenu();
          } else {
            this.onMinimizeToolbarBtnClick();
          }
        }

        // Add keyboard shortcuts handlers for custom markdown
        // editor toolbar buttons: image upload (ctrl+p),
        // formulas (ctrl+f), minimize (ctrl+m)
        // Needs to be done here because TUI editor currently
        // doesn't support customizing shortcuts
        // https://github.com/nhn/tui.editor/issues/281
        if (event.ctrlKey === true && event.key === 'p') {
          event.stopImmediatePropagation();
          this.onImageUploadToolbarBtnClick();
        }

        if (event.ctrlKey === true && event.key === 'f') {
          this.onFormulasToolbarBtnClick();
        }

        if (event.ctrlKey === true && event.key === 'm') {
          this.onMinimizeToolbarBtnClick();
        }

        // Allow default keyboard shortcut handlers
        // for supported actions: bold (ctrl+b), italics (ctrl+i),
        // select all (ctrl+a), copy (ctrl+c),
        // cut (ctrl+x), paste (ctrl+v)
        // Disable all remaining default keyboard shortcuts.
        if (event.ctrlKey === true && ['b', 'i', 'a', 'c', 'x', 'v', 'z'].includes(event.key)) {
          return;
        }

        // Disable all remaining Ctrl key shortcuts
        if (event.ctrlKey === true) {
          event.preventDefault();
          event.stopPropagation();
        }

        this.updateCustomNodeSpacers();
      },
      onPaste(event) {
        const fragment = clearNodeFormat({
          node: event.fragment,
          ignore: ['b', 'i'],
        });
        event.fragment = fragment;
      },
      onImageDrop(file) {
        this.activeImageComponent = null;
        this.highlight = false;

        const cursor = this.getCursor();
        const position = getExtensionMenuPosition({
          editorEl: this.$el,
          targetX: cursor.x,
          targetY: cursor.y + cursor.height,
        });
        this.resetImagesMenu();
        this.openImagesMenu({ position });

        // need to wait for the images menu component
        this.$nextTick(() => {
          this.$refs.imagesMenu.handleFiles([file]);
        });
      },
      onImageUploadToolbarBtnClick() {
        if (this.imagesMenu.isOpen === true) {
          return;
        }
        this.activeImageField = null;

        const cursor = this.getCursor();
        const position = getExtensionMenuPosition({
          editorEl: this.$el,
          targetX: cursor.x,
          targetY: cursor.y + cursor.height,
        });
        this.resetImagesMenu();
        this.openImagesMenu({ position });
      },
      onFormulasToolbarBtnClick() {
        if (this.formulasMenu.isOpen === true) {
          return;
        }

        const cursor = this.getCursor();
        const formulasMenuPosition = getExtensionMenuPosition({
          editorEl: this.$el,
          targetX: cursor.x,
          targetY: cursor.y + cursor.height,
        });

        this.resetFormulasMenu();
        this.openFormulasMenu({ position: formulasMenuPosition });
      },
      onMinimizeToolbarBtnClick() {
        this.$emit('minimize');
        // Make sure tooltip gets removed from screen
        document.querySelectorAll('.tui-tooltip').forEach(tooltip => {
          tooltip.style.display = 'none';
        });
      },
      getCursor() {
        return this.editor.getSquire().getCursorPosition();
      },
      fixSquireSelectionOnKeyDown(event) {
        /**
         *  On 'backspace' events, Squire doesn't behave consistently in both Chrome and FireFox,
         *  particularly when dealing with custom elements or elements with `contenteditable=false`.
         *
         *  This function modifies the selection with the intention of correcting it before Squire
         *  handles it in the usual way.
         *
         *  This is a tricky workaround, so please edit this function with care.
         */

        const squire = this.editor.getSquire();
        const selection = squire.getSelection();

        // Prevent Squire from deleting custom editor nodes when the cursor is left of one.
        const isCustomNode = node => node && node.hasAttribute && node.hasAttribute('is');

        const getElementAtRelativeOffset = (selection, offset) =>
          selection &&
          squire.getSelectionInfoByOffset(selection.endContainer, selection.endOffset + offset)
            .element;

        const getLeftwardElement = selection => getElementAtRelativeOffset(selection, -1);
        const getRightwardElement = selection => getElementAtRelativeOffset(selection, 1);

        const getCharacterAtRelativeOffset = (selection, relativeOffset) => {
          let { element, offset } = squire.getSelectionInfoByOffset(
            selection.startContainer,
            selection.startOffset + relativeOffset
          );
          return element.nodeType === document.TEXT_NODE && element.textContent[offset];
        };

        const spacerAndCustomElementAreLeftward = selection =>
          selection &&
          isCustomNode(getElementAtRelativeOffset(selection, -2)) &&
          selection.startContainer.nodeType === document.TEXT_NODE &&
          getCharacterAtRelativeOffset(selection, -1) &&
          /^\s/.test(getCharacterAtRelativeOffset(selection, -1));

        const spacerAndCustomElementAreRightward = selection =>
          selection &&
          isCustomNode(getElementAtRelativeOffset(selection, 2)) &&
          selection.startContainer.nodeType === document.TEXT_NODE &&
          getCharacterAtRelativeOffset(selection, 0) &&
          /\s$/.test(getCharacterAtRelativeOffset(selection, 0));

        const moveCursor = (selection, amount) => {
          let { element, offset } = squire.getSelectionInfoByOffset(
            selection.startContainer,
            selection.startOffset + amount
          );
          if (amount > 0) {
            selection.setStart(element, offset);
          } else {
            selection.setEnd(element, offset);
          }
          return selection;
        };

        // make sure Squire doesn't delete rightward custom nodes when 'backspace' is pressed
        if (event.key !== 'ArrowRight' && event.key !== 'Delete') {
          if (isCustomNode(getRightwardElement(selection))) {
            squire.setSelection(moveCursor(selection, -1));
          }
        }
        // make sure Squire doesn't get stuck with a broken cursor position when deleting
        // elements with `contenteditable="false"` in FireFox
        let leftwardElement = getLeftwardElement(selection);
        if (event.key === 'Backspace') {
          if (selection.startContainer.tagName === 'DIV') {
            // This happens normally when deleting from the beginning of an empty line...
            if (isCustomNode(selection.startContainer.childNodes[selection.startOffset - 1])) {
              // ...but on FireFox it also happens if you press 'backspace' and the leftward
              // element has `contenteditable="false"` (which is necessary on FireFox for
              // a different reason).  As a result, Squire.js gets stuck. The trick here is
              // to fix its selection so it knows what to delete.
              let fixedStartContainer =
                selection.startContainer.childNodes[selection.startOffset - 1];
              let fixedEndContainer = selection.endContainer.childNodes[selection.endOffset - 1];
              if (fixedStartContainer && fixedEndContainer) {
                selection.setStart(fixedStartContainer, 0);
                selection.setEnd(fixedEndContainer, 1);
                squire.setSelection(selection);
              }
            }
          } else if (isCustomNode(leftwardElement)) {
            // In general, if the cursor is to the right of a custom node and 'backspace'
            // is pressed, add that node to the selection so that it will be deleted.
            selection.setStart(leftwardElement, 0);
            squire.setSelection(selection);
          } else if (spacerAndCustomElementAreLeftward(selection)) {
            // if there's a custom node and a spacer, delete them both
            selection.setStart(getElementAtRelativeOffset(selection, -2), 0);
            squire.setSelection(selection);
          }
        } else if (event.key === 'Delete') {
          if (spacerAndCustomElementAreRightward(selection)) {
            // if there's a custom node and a spacer, delete them both
            selection.setEnd(getElementAtRelativeOffset(selection, 2).nextSibling, 1);
            squire.setSelection(selection);
          }
        }
        // the cursor will get stuck if it's inside of a non-contentEditable parent
        if (!selection.startContainer.parentElement.isContentEditable) {
          selection.setStart(selection.startContainer.parentElement, 0);
        }
        if (!selection.endContainer.parentElement.isContentEditable) {
          selection.setEnd(selection.endContainer.parentElement, 0);
        }
        // if any part of a custom node is in the selection, include the whole thing
        if (isCustomNode(selection.startContainer)) {
          let previousSibling = selection.startContainer.previousSibling;
          selection.setStart(previousSibling, previousSibling.length - 1);
          squire.setSelection(selection);
        }
        if (isCustomNode(selection.endContainer)) {
          selection.setEnd(selection.endContainer.nextSibling, 1);
          squire.setSelection(selection);
        }
        // Important debugging tip... If the editor selection is broken,
        // uncomment the following line to understand how it got that way:
        // console.log("keypress", selection, event);
      },
      onClick(event) {
        this.highlight = false;
        const target = event.target;

        let mathFieldEl = null;
        if (target.getAttribute('is') === 'markdown-formula-field') {
          mathFieldEl = target;
        }
        const clickedOnMathField = mathFieldEl !== null;
        const clickedOnActiveMathField =
          clickedOnMathField &&
          mathFieldEl.classList &&
          mathFieldEl.classList.contains(CLASS_MATH_FIELD_ACTIVE);
        const clickedOnFormulasMenu =
          (target.classList && target.classList.contains('formulas-menu')) ||
          target.closest('.formulas-menu');
        const clickedOnImagesMenu =
          (target.classList && target.classList.contains('images-menu')) ||
          target.closest('.images-menu');
        const clickedOnEditorToolbarBtn =
          target.classList && target.classList.contains('tui-toolbar-icons');

        // skip markdown editor toolbar buttons clicks
        // they have their own handlers defined
        if (clickedOnEditorToolbarBtn) {
          return;
        }

        // no need to do anything when the formulas menu clicked
        if (clickedOnFormulasMenu) {
          return;
        }

        // no need to do anything when an active math field clicked
        if (clickedOnActiveMathField) {
          return;
        }

        // no need to do anything when the images menu clicked
        if (clickedOnImagesMenu) {
          return;
        }

        // if clicked outside of open formulas menu
        // and active math field then close the formulas
        // menu and clear data related to its previous state
        if (this.formulasMenu.isOpen) {
          this.insertFormulaToEditor();
          this.removeMathFieldActiveClass();
          this.resetFormulasMenu();
        }

        // if clicked outside of open images menu close images
        // menu and clear data related to its previous state
        if (this.imagesMenu.isOpen) {
          this.resetImagesMenu();
        }

        // no need to continue if regular text clicked
        if (!clickedOnMathField) {
          return;
        }

        // open formulas menu if a math field clicked
        const formulasMenuPosition = getExtensionMenuPosition({
          editorEl: this.$el,
          targetX: mathFieldEl.getBoundingClientRect().left,
          targetY: mathFieldEl.getBoundingClientRect().bottom,
        });

        // get current formula from the custom element's underlying vue instance
        const formulasMenuFormula = mathFieldEl.getVueInstance().latex;

        // just a little visual enhancement to make clear
        // that the formula menu is linked to a math field
        // element being edited
        if (formulasMenuPosition.left !== null) {
          formulasMenuPosition.left += 10;
        }
        if (formulasMenuPosition.right !== null) {
          formulasMenuPosition.right -= 10;
        }

        mathFieldEl.classList.add(CLASS_MATH_FIELD_ACTIVE);

        // `nextTick` - to be sure that the formula
        // was reset before a new formula set
        // important when a math field is being edited in open
        // formulas menu and another math field is clicked
        this.$nextTick(() => {
          this.openFormulasMenu({
            position: formulasMenuPosition,
            formula: formulasMenuFormula,
          });
        });
      },
      onFormulasMenuInsert() {
        this.insertFormulaToEditor();
        const formula = this.formulasMenu.formula;

        this.removeMathFieldActiveClass();
        this.resetFormulasMenu();
        this.editor.focus();

        if (formula) {
          this.trackAnalyticsEvent('Select formula', formula);
        }

        this.trackAnalyticsEvent('Add', 'Formula');
      },
      onFormulasMenuCancel() {
        this.removeMathFieldActiveClass();
        this.resetFormulasMenu();
        this.editor.focus();
      },
      // Set `markdown-formula-field` components with `editing=true`.
      initMathFields() {
        this.$el.querySelectorAll('span[is="markdown-formula-field"]').forEach(el => {
          el.editing = true;
        });
      },
      findActiveMathField() {
        return this.$el.getElementsByClassName(CLASS_MATH_FIELD_ACTIVE)[0] || null;
      },
      removeMathFieldActiveClass() {
        const activeMathField = this.findActiveMathField();

        if (activeMathField !== null) {
          activeMathField.classList.remove(CLASS_MATH_FIELD_ACTIVE);
        }
      },
      openFormulasMenu({ position, formula = null }) {
        this.resetMenus();
        const top = `${position.top}px`;

        let left, right, anchorArrowSide;

        if (position.left !== null) {
          right = 'initial';
          left = `${position.left}px`;
          anchorArrowSide = this.$isRTL ? 'right' : 'left';
        } else {
          left = 'initial';
          right = `${position.right}px`;
          anchorArrowSide = this.$isRTL ? 'left' : 'right';
        }

        this.formulasMenu = {
          isOpen: true,
          formula: formula !== null ? formula : '',
          anchorArrowSide,
          style: {
            top,
            left,
            right,
          },
        };

        this.trackAnalyticsEvent('Open', 'Formula panel');
      },
      /**
       * Insert formula from formulas menu to markdown editor.
       * If there is an active math field, replace it by a new
       * element with the updated formula. Otherwise insert a new
       * element with the formula on a current cursor position.
       */
      insertFormulaToEditor() {
        const formula = this.formulasMenu.formula;

        if (!formula) {
          return;
        }

        const formulaEl = document.createElement('span');
        formulaEl.setAttribute('is', 'markdown-formula-field');
        formulaEl.setAttribute('editing', true);
        formulaEl.innerHTML = formula;
        let formulaHTML = formulaEl.outerHTML;
        const activeMathFieldEl = this.findActiveMathField();

        if (activeMathFieldEl !== null) {
          // setting `outerHTML` is the preferred way to reset a custom node
          activeMathFieldEl.outerHTML = formulaHTML;
        } else {
          let squire = this.editor.getSquire();
          squire.insertHTML(formulaHTML);
          this.updateCustomNodeSpacers();
        }
      },
      resetFormulasMenu() {
        this.formulasMenu = {
          isOpen: false,
          formula: '',
          anchorArrowSide: null,
          style: {
            top: 'initial',
            left: 'initial',
            right: 'initial',
          },
        };
      },

      /* IMAGE MENU */
      handleEditImage(event) {
        let { editorField, editEvent, image } = event.detail;
        this.activeImageField = editorField;
        let editorEl = this.$el;
        let position = getExtensionMenuPosition({
          editorEl,
          targetX: editEvent.clientX,
          targetY: editEvent.clientY,
        });
        this.openImagesMenu({
          position,
          alt: image.alt,
          src: image.src,
        });
      },
      // set `markdown-image-field` components with `editing=true`
      initImageFields() {
        this.$el.querySelectorAll('span[is="markdown-image-field"]').forEach(imageEl => {
          imageEl.editing = true;
        });
      },
      openImagesMenu({ position, src = '', alt = '' }) {
        this.resetMenus();
        const top = `${position.top}px`;

        let left, right, anchorArrowSide;

        if (position.left !== null) {
          right = 'initial';
          left = `${position.left}px`;
          anchorArrowSide = this.$isRTL ? 'right' : 'left';
        } else {
          left = 'initial';
          right = `${position.right}px`;
          anchorArrowSide = this.$isRTL ? 'left' : 'right';
        }

        this.imagesMenu = {
          isOpen: true,
          anchorArrowSide,
          src,
          alt,
          style: {
            top,
            left,
            right,
          },
        };
        this.trackAnalyticsEvent('Open', 'Image modal');
      },
      /**
       * Insert image from images menu to markdown editor.
       * Emit an uploaded event to let parent process files
       * properly
       */
      insertImageToEditor(imageData) {
        const mdImageFieldHTML = paramsToImageFieldHTML(imageData);
        if (!imageData) {
          return;
        }
        if (this.activeImageField) {
          this.activeImageField.outerHTML = mdImageFieldHTML;
        } else {
          const template = document.createElement('template');
          template.innerHTML = mdImageFieldHTML;
          const mdImageEl = template.content.firstElementChild;
          mdImageEl.setAttribute('editing', true);

          // insert non-breaking spaces to allow users to write text before and after
          this.editor.getSquire().insertHTML(wrapWithSpaces(mdImageEl.outerHTML));

          this.initImageFields();
        }
        this.resetImagesMenu();
        this.trackAnalyticsEvent('Add', 'Image');
      },
      onImagesMenuCancel() {
        this.resetImagesMenu();
        this.editor.focus();
      },
      resetImagesMenu() {
        this.imagesMenu = {
          isOpen: false,
          anchorArrowSide: null,
          src: '',
          alt: '',
          style: {
            top: 'initial',
            left: 'initial',
            right: 'initial',
          },
        };
      },
      resetMenus() {
        this.resetImagesMenu();
        this.resetFormulasMenu();
      },
      trackAnalyticsEvent(name, eventLabel = null) {
        eventLabel = eventLabel || this.analyticsLabel;

        if (eventLabel) {
          this.$analytics.trackAction('exercise_editor', name, {
            eventLabel,
          });
        }
      },
    },
    $trs: {
      bold: 'Bold (Ctrl+B)',
      italic: 'Italic (Ctrl+I)',
      image: 'Insert image (Ctrl+P)',
      formulas: 'Insert formula (Ctrl+F)',
      minimize: 'Minimize (Ctrl+M)',
    },
  };

</script>

<style lang="less" scoped>

  @import '../mathquill/mathquill.css';

  .editor {
    margin: 1px;
  }

  .uploading {
    cursor: progress;
  }

  .formulas-menu,
  .images-menu {
    z-index: 2;
  }

  .wrapper {
    padding: 1px;
    border: 4px solid transparent;
    &.highlight {
      border-color: var(--v-primary-base);
    }
  }

  // TODO (when updating to new frontend files structure)
  // find better location for following styles that
  // are supposed to be common to all editable fields
  /deep/ .mq-editable-field {
    border: 0;

    .mq-to,
    .mq-from,
    .mq-sup,
    .mq-sup-inner,
    .mq-sub,
    .mq-numerator,
    .mq-denominator {
      padding-right: 1px;
      padding-left: 1px;
      border: 1px solid gray;
    }

    .mq-int .mq-sup {
      border: 0;
    }
  }

</style>
