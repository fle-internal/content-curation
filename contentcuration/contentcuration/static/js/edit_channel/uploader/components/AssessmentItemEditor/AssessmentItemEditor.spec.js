import { shallowMount, mount } from '@vue/test-utils';

import { AssessmentItemTypes, AssessmentItemValidationErrors } from '../../constants';
import AssessmentItemEditor from './AssessmentItemEditor';

jest.mock('../MarkdownEditor/MarkdownEditor.vue');

const ITEM = {
  data: {
    question: 'Exercise 2 - Question 2',
    type: AssessmentItemTypes.SINGLE_SELECTION,
    answers: [
      { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
      { answer: 'Peanut butter', correct: false, order: 2 },
    ],
    hints: [{ hint: "It's not healthy", order: 1 }, { hint: 'Tasty!', order: 2 }],
  },
  validation: {},
};

const openQuestion = wrapper => {
  wrapper.find('[data-test="questionText"]').trigger('click');
};

const updateQuestion = (wrapper, newQuestionText) => {
  // only one editor is rendered at a time => "wrapper.find"
  wrapper.find({ name: 'MarkdownEditor' }).vm.$emit('update', newQuestionText);
};

const selectKind = (wrapper, kind) => {
  const input = wrapper.find('[data-test="kindSelect"]');
  input.element.value = kind;

  input.trigger('input');
};

describe('AssessmentItemEditor', () => {
  let wrapper;

  it('smoke test', () => {
    const wrapper = shallowMount(AssessmentItemEditor);

    expect(wrapper.isVueInstance()).toBe(true);
  });

  it('renders', () => {
    wrapper = mount(AssessmentItemEditor, {
      propsData: {
        item: ITEM,
      },
    });

    expect(wrapper.html()).toMatchSnapshot();
  });

  describe('on question text update', () => {
    beforeEach(() => {
      wrapper = mount(AssessmentItemEditor, {
        propsData: {
          item: ITEM,
        },
      });

      openQuestion(wrapper);
      updateQuestion(wrapper, 'My new question');
    });

    it('emits update event with item containing updated question text', () => {
      expect(wrapper.emitted().update).toBeTruthy();
      expect(wrapper.emitted().update.length).toBe(1);
      expect(wrapper.emitted().update[0][0]).toEqual({
        ...ITEM,
        data: {
          ...ITEM.data,
          question: 'My new question',
        },
      });
    });
  });

  describe('on item type update', () => {
    describe('when changing to single selection', () => {
      beforeEach(() => {
        const item = JSON.parse(JSON.stringify(ITEM));
        item.data = {
          ...item.data,
          type: AssessmentItemTypes.MULTIPLE_SELECTION,
          answers: [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: true, order: 2 },
          ],
        };

        wrapper = mount(AssessmentItemEditor, {
          propsData: {
            item,
          },
        });

        selectKind(wrapper, AssessmentItemTypes.SINGLE_SELECTION);
      });

      it('emits update event with item containing updated answers and type', () => {
        expect(wrapper.emitted().update).toBeTruthy();
        expect(wrapper.emitted().update.length).toBe(1);
        expect(wrapper.emitted().update[0][0]).toEqual({
          ...ITEM,
          data: {
            ...ITEM.data,
            answers: [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
              { answer: 'Peanut butter', correct: false, order: 2 },
            ],
            type: AssessmentItemTypes.SINGLE_SELECTION,
          },
          validation: {},
        });
      });
    });

    describe('when changing to multiple selection', () => {
      beforeEach(() => {
        const item = JSON.parse(JSON.stringify(ITEM));
        item.data = {
          ...item.data,
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: false, order: 2 },
          ],
        };

        wrapper = mount(AssessmentItemEditor, {
          propsData: {
            item,
          },
        });

        selectKind(wrapper, AssessmentItemTypes.MULTIPLE_SELECTION);
      });

      it('emits update event with item containing same answers and type', () => {
        expect(wrapper.emitted().update).toBeTruthy();
        expect(wrapper.emitted().update.length).toBe(1);
        expect(wrapper.emitted().update[0][0]).toEqual({
          ...ITEM,
          data: {
            ...ITEM.data,
            answers: [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
              { answer: 'Peanut butter', correct: false, order: 2 },
            ],
            type: AssessmentItemTypes.MULTIPLE_SELECTION,
          },
        });
      });
    });

    describe('when changing to true/false', () => {
      beforeEach(() => {
        const item = JSON.parse(JSON.stringify(ITEM));
        item.data = {
          ...item.data,
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: false, order: 2 },
          ],
        };

        wrapper = mount(AssessmentItemEditor, {
          propsData: {
            item,
          },
        });

        selectKind(wrapper, AssessmentItemTypes.TRUE_FALSE);
      });

      it('emits update event with item containing updated answers and type', () => {
        expect(wrapper.emitted().update).toBeTruthy();
        expect(wrapper.emitted().update.length).toBe(1);
        expect(wrapper.emitted().update[0][0]).toEqual({
          ...ITEM,
          data: {
            ...ITEM.data,
            answers: [
              { answer: 'True', order: 1, correct: true },
              { answer: 'False', order: 2, correct: false },
            ],
            type: AssessmentItemTypes.TRUE_FALSE,
          },
        });
      });
    });

    describe('when changing to input question', () => {
      beforeEach(() => {
        const item = JSON.parse(JSON.stringify(ITEM));
        item.data = {
          ...item.data,
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: false, order: 2 },
          ],
        };

        wrapper = mount(AssessmentItemEditor, {
          propsData: {
            item,
          },
        });

        selectKind(wrapper, AssessmentItemTypes.INPUT_QUESTION);
      });

      it('emits update event with item containing updated answers and type', () => {
        expect(wrapper.emitted().update).toBeTruthy();
        expect(wrapper.emitted().update.length).toBe(1);
        expect(wrapper.emitted().update[0][0]).toEqual({
          ...ITEM,
          data: {
            ...ITEM.data,
            answers: [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
              { answer: 'Peanut butter', correct: true, order: 2 },
            ],
            type: AssessmentItemTypes.INPUT_QUESTION,
          },
        });
      });
    });
  });

  describe('on answers update', () => {
    beforeEach(() => {
      let item = JSON.parse(JSON.stringify(ITEM));
      item.data = {
        ...item.data,
        type: AssessmentItemTypes.SINGLE_SELECTION,
        answers: [
          { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
          { answer: 'Peanut butter', correct: false, order: 2 },
        ],
      };

      wrapper = mount(AssessmentItemEditor, {
        propsData: {
          item,
        },
      });

      const newAnswers = [
        { answer: 'Mayonnaise (I mean you can, but...)', correct: false, order: 1 },
        { answer: 'Peanut butter', correct: false, order: 2 },
      ];

      wrapper.find({ name: 'AnswersEditor' }).vm.$emit('update', newAnswers);
    });

    it('emits update event with an item containing updated answers', () => {
      expect(wrapper.emitted().update).toBeTruthy();
      expect(wrapper.emitted().update.length).toBe(1);
      expect(wrapper.emitted().update[0][0]).toEqual({
        ...ITEM,
        data: {
          ...ITEM.data,
          answers: [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: false, order: 1 },
            { answer: 'Peanut butter', correct: false, order: 2 },
          ],
        },
      });
    });
  });

  describe('on hints update', () => {
    beforeEach(() => {
      let item = JSON.parse(JSON.stringify(ITEM));
      item.data = {
        ...item.data,
        hints: [{ hint: 'Hint 1', order: 1 }],
      };

      wrapper = mount(AssessmentItemEditor, {
        propsData: {
          item,
        },
      });

      const newHints = [{ hint: 'Hint 1', order: 1 }, { hint: 'Hint 2', order: 2 }];

      wrapper.find({ name: 'HintsEditor' }).vm.$emit('update', newHints);
    });

    it('emits update event with item containing updated hints', () => {
      expect(wrapper.emitted().update).toBeTruthy();
      expect(wrapper.emitted().update.length).toBe(1);
      expect(wrapper.emitted().update[0][0]).toEqual({
        ...ITEM,
        data: {
          ...ITEM.data,
          hints: [{ hint: 'Hint 1', order: 1 }, { hint: 'Hint 2', order: 2 }],
        },
      });
    });
  });

  describe('for an invalid item', () => {
    beforeEach(() => {
      const item = JSON.parse(JSON.stringify(ITEM));
      (item.validation = {
        questionErrors: [AssessmentItemValidationErrors.BLANK_QUESTION],
        answersErrors: [AssessmentItemValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS],
      }),
        (wrapper = mount(AssessmentItemEditor, {
          propsData: {
            item,
          },
        }));
    });

    it('renders all errors messages', () => {
      expect(wrapper.find('[data-test=questionErrors]')).toMatchSnapshot();
      expect(wrapper.find('[data-test=answersErrors]')).toMatchSnapshot();
    });
  });
});
