import each from 'jest-each';
import { AssessmentItemTypes, ValidationErrors } from '../constants';
import {
  validateNodeDetails,
  validateNodeFiles,
  sanitizeAssessmentItemAnswers,
  sanitizeAssessmentItemHints,
  sanitizeAssessmentItem,
  validateAssessmentItem,
  getCorrectAnswersIndices,
  mapCorrectAnswers,
  updateAnswersToQuestionType,
} from '../utils';

describe('channelEdit utils', () => {
  describe('validateNodeDetails', () => {
    it('returns a correct error code when title missing', () => {
      expect(
        validateNodeDetails({
          title: '',
          kind: 'document',
          license: 8,
        })
      ).toEqual([ValidationErrors.TITLE_REQUIRED]);
    });

    each([
      [
        {
          title: 'Title',
          kind: 'document',
          license: null,
        },
        [ValidationErrors.LICENCE_REQUIRED],
      ],
      [
        {
          title: 'Title',
          kind: 'document',
          license: 8,
        },
        [],
      ],
      // license is not required for topics
      [
        {
          title: 'Title',
          kind: 'topic',
          license: null,
        },
        [],
      ],
      // license is not required when authoring data freezed
      [
        {
          title: 'Title',
          freeze_authoring_data: true,
          license: null,
        },
        [],
      ],
    ]).it('validates license presence', (node, errors) => {
      expect(validateNodeDetails(node)).toEqual(errors);
    });

    each([
      // copyright holder is required for licences other than Public Domain
      [
        {
          title: 'Title',
          license: 1,
        },
        [ValidationErrors.COPYRIGHT_HOLDER_REQUIRED],
      ],
      [
        {
          title: 'Title',
          license: 1,
          copyright_holder: 'Copyright holder',
        },
        [],
      ],
    ]).it('validates copyright holder', (node, errors) => {
      expect(validateNodeDetails(node)).toEqual(errors);
    });

    each([
      // description is required for a custom license
      [
        {
          title: 'Title',
          license: 9,
          copyright_holder: 'Copyright holder',
        },
        [ValidationErrors.LICENCE_DESCRIPTION_REQUIRED],
      ],
      [
        {
          title: 'Title',
          license: 9,
          copyright_holder: 'Copyright holder',
          license_description: 'My custom license',
        },
        [],
      ],
    ]).it('validates license description', (node, errors) => {
      expect(validateNodeDetails(node)).toEqual(errors);
    });

    each([
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
        },
        [ValidationErrors.MASTERY_MODEL_REQUIRED],
      ],
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
          extra_fields: {
            mastery_model: 'do_all',
          },
        },
        [],
      ],
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
          extra_fields: {
            mastery_model: 'm_of_n',
            m: 3,
          },
        },
        [ValidationErrors.MASTERY_MODEL_INVALID],
      ],
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
          extra_fields: {
            mastery_model: 'm_of_n',
            m: 3,
            n: 2,
          },
        },
        [ValidationErrors.MASTERY_MODEL_INVALID],
      ],
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
          extra_fields: {
            mastery_model: 'm_of_n',
            m: 2,
            n: 3,
          },
        },
        [],
      ],
    ]).it('validates mastery model for exercises', (node, errors) => {
      expect(validateNodeDetails(node)).toEqual(errors);
    });
  });

  describe('validateNodeFiles', () => {
    it('throws an error if there are no valid primary files', () => {
      let testFiles = [
        {
          error: ValidationErrors.UPLOAD_FAILED,
          preset: { supplementary: false },
        },
        {
          error: ValidationErrors.UPLOAD_FAILED,
          preset: { supplementary: false },
        },
        {
          preset: { supplementary: true },
        },
      ];
      expect(validateNodeFiles(testFiles)).toContain(ValidationErrors.NO_VALID_PRIMARY_FILES);
    });
    it('does not throw NO_VALID_PRIMARY_FILES if there is one valid primary file', () => {
      let testFiles = [
        {
          error: ValidationErrors.UPLOAD_FAILED,
          preset: { supplementary: false },
        },
        {
          preset: { supplementary: false },
        },
      ];
      expect(validateNodeFiles(testFiles)).not.toContain(ValidationErrors.NO_VALID_PRIMARY_FILES);
    });
    it('returns array of errors found on files', () => {
      let testFiles = [
        {
          error: ValidationErrors.NO_STORAGE,
          preset: { supplementary: true },
        },
        {
          error: ValidationErrors.UPLOAD_FAILED,
          preset: { supplementary: true },
        },
        {
          preset: { supplementary: false },
        },
      ];
      let expectedErrors = [ValidationErrors.NO_STORAGE, ValidationErrors.UPLOAD_FAILED];
      expect(validateNodeFiles(testFiles)).toEqual(expectedErrors);
    });
  });

  describe('sanitizeAssessmentItemAnswers', () => {
    it('trims answers', () => {
      const answers = [
        { answer: '', order: 1, correct: true },
        { answer: ' 3 ', order: 2, correct: false },
        { answer: '  ', order: 3, correct: true },
      ];

      expect(sanitizeAssessmentItemAnswers(answers)).toEqual([
        { answer: '', order: 1, correct: true },
        { answer: '3', order: 2, correct: false },
        { answer: '', order: 3, correct: true },
      ]);
    });

    it('removes all empty answers and reorders remaining answers if removeEmpty true', () => {
      const answers = [
        { answer: '', order: 1, correct: true },
        { answer: ' 3 ', order: 2, correct: false },
        { answer: '  ', order: 3, correct: true },
      ];

      expect(sanitizeAssessmentItemAnswers(answers, true)).toEqual([
        { answer: '3', order: 1, correct: false },
      ]);
    });
  });

  describe('sanitizeAssessmentItemHints', () => {
    it('trims hints', () => {
      const hints = [
        { hint: '', order: 1 },
        { hint: ' Hint 1 ', order: 2 },
        { hint: '  ', order: 3 },
      ];

      expect(sanitizeAssessmentItemHints(hints)).toEqual([
        { hint: '', order: 1 },
        { hint: 'Hint 1', order: 2 },
        { hint: '', order: 3 },
      ]);
    });

    it('removes all empty hints and reorders remaining hints if removeEmpty true', () => {
      const hints = [
        { hint: '', order: 1 },
        { hint: ' Hint 1 ', order: 2 },
        { hint: '  ', order: 3 },
      ];

      expect(sanitizeAssessmentItemHints(hints, true)).toEqual([{ hint: 'Hint 1', order: 1 }]);
    });
  });

  describe('sanitizeAssessmentItem', () => {
    it('trims question, hints and answers', () => {
      const assessmentItem = {
        order: 1,
        question: ' Question text ',
        answers: [
          { answer: ' Answer 1', order: 1, correct: false },
          { answer: '', order: 2, correct: true },
          { answer: 'Answer 3    ', order: 3, correct: true },
        ],
        hints: [
          { hint: ' ', order: 1 },
          { hint: '', order: 2 },
          { hint: ' Hint 3', order: 3 },
        ],
      };

      expect(sanitizeAssessmentItem(assessmentItem)).toEqual({
        order: 1,
        question: 'Question text',
        answers: [
          { answer: 'Answer 1', order: 1, correct: false },
          { answer: '', order: 2, correct: true },
          { answer: 'Answer 3', order: 3, correct: true },
        ],
        hints: [
          { hint: '', order: 1 },
          { hint: '', order: 2 },
          { hint: 'Hint 3', order: 3 },
        ],
      });
    });

    it('removes all empty hints and answers if removeEmpty true', () => {
      const assessmentItem = {
        order: 1,
        question: ' Question text ',
        answers: [
          { answer: ' Answer 1', order: 1, correct: false },
          { answer: '', order: 2, correct: true },
          { answer: 'Answer 3    ', order: 3, correct: true },
        ],
        hints: [
          { hint: ' ', order: 1 },
          { hint: '', order: 2 },
          { hint: ' Hint 3', order: 3 },
        ],
      };

      expect(sanitizeAssessmentItem(assessmentItem, true)).toEqual({
        order: 1,
        question: 'Question text',
        answers: [
          { answer: 'Answer 1', order: 1, correct: false },
          { answer: 'Answer 3', order: 2, correct: true },
        ],
        hints: [{ hint: 'Hint 3', order: 1 }],
      });
    });
  });

  describe('validateAssessmentItem', () => {
    describe('when question text is missing', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: '',
          answers: [{ answer: 'Answer', correct: true, order: 1 }],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.QUESTION_REQUIRED,
        ]);
      });
    });

    describe('for single selection with no answers', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for single selection with no correct answer', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [{ answer: 'Answer', correct: false, order: 1 }],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for single selection with more correct answers', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [
            { answer: 'Answer 1', correct: true, order: 1 },
            { answer: 'Answer 2', correct: true, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for single selection with one correct answer', () => {
      it('returns positive validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.SINGLE_SELECTION,
          answers: [
            { answer: 'Answer 1', correct: false, order: 1 },
            { answer: 'Answer 2', correct: true, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([]);
      });
    });

    describe('for multiple selection with no answers', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.MULTIPLE_SELECTION,
          answers: [],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for multiple selection with no correct answer', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.MULTIPLE_SELECTION,
          answers: [
            { answer: 'Answer 1', correct: false, order: 1 },
            { answer: 'Answer 2', correct: false, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for multiple selection with at least one correct answer', () => {
      it('returns positive validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.MULTIPLE_SELECTION,
          answers: [
            { answer: 'Answer 1', correct: true, order: 1 },
            { answer: 'Answer 2', correct: false, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([]);
      });
    });

    describe('for input question with no answers', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.INPUT_QUESTION,
          answers: [],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for input question with no correct answer', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.INPUT_QUESTION,
          answers: [
            { answer: 'Answer 1', correct: false, order: 1 },
            { answer: 'Answer 2', correct: false, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for input question with at least one correct answer', () => {
      it('returns positive validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.INPUT_QUESTION,
          answers: [
            { answer: 'Answer 1', correct: true, order: 1 },
            { answer: 'Answer 2', correct: true, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([]);
      });
    });

    describe('for true/false with no answers', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.TRUE_FALSE,
          answers: [],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for true/false with no correct answer', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.TRUE_FALSE,
          answers: [
            { answer: 'True', correct: false, order: 1 },
            { answer: 'False', correct: false, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for true/false with more correct answers', () => {
      it('returns negative validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.TRUE_FALSE,
          answers: [
            { answer: 'True', correct: true, order: 1 },
            { answer: 'False', correct: true, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([
          ValidationErrors.INVALID_NUMBER_OF_CORRECT_ANSWERS,
        ]);
      });
    });

    describe('for true/false with one correct answer', () => {
      it('returns positive validation results', () => {
        const assessmentItem = {
          question: 'Question',
          type: AssessmentItemTypes.TRUE_FALSE,
          answers: [
            { answer: 'True', correct: false, order: 1 },
            { answer: 'False', correct: true, order: 2 },
          ],
        };

        expect(validateAssessmentItem(assessmentItem)).toEqual([]);
      });
    });
  });

  describe('getCorrectAnswersIndices', () => {
    let questionKind;

    describe('for a single selection question', () => {
      beforeEach(() => {
        questionKind = AssessmentItemTypes.SINGLE_SELECTION;
      });

      it('returns null if there is no correct answer', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'Answer 1', correct: false },
            { answer: 'Answer 2', correct: false },
          ])
        ).toBeNull();
      });

      it('returns a correct answer index', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'Answer 1', correct: false },
            { answer: 'Answer 2', correct: true },
          ])
        ).toBe(1);
      });
    });

    describe('for a true/false question', () => {
      beforeEach(() => {
        questionKind = AssessmentItemTypes.TRUE_FALSE;
      });

      it('returns null if there is no correct answer', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'True', correct: false },
            { answer: 'False', correct: false },
          ])
        ).toBeNull();
      });

      it('returns a correct answer index', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'True', correct: false },
            { answer: 'False', correct: true },
          ])
        ).toBe(1);
      });
    });

    describe('for a multiple selection question', () => {
      beforeEach(() => {
        questionKind = AssessmentItemTypes.MULTIPLE_SELECTION;
      });

      it('returns an empty array if there is no correct answer', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'Answer 1', correct: false },
            { answer: 'Answer 2', correct: false },
            { answer: 'Answer 3', correct: false },
          ])
        ).toEqual([]);
      });

      it('returns an array of correct answer indices', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'Answer 1', correct: true },
            { answer: 'Answer 2', correct: false },
            { answer: 'Answer 3', correct: true },
          ])
        ).toEqual([0, 2]);
      });
    });

    describe('for an input question', () => {
      beforeEach(() => {
        questionKind = AssessmentItemTypes.INPUT_QUESTION;
      });

      it('returns an empty array if there is no correct answer', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'Answer 1', correct: false },
            { answer: 'Answer 2', correct: false },
            { answer: 'Answer 3', correct: false },
          ])
        ).toEqual([]);
      });

      it('returns an array of correct answer indices', () => {
        expect(
          getCorrectAnswersIndices(questionKind, [
            { answer: 'Answer 1', correct: true },
            { answer: 'Answer 2', correct: true },
            { answer: 'Answer 3', correct: true },
          ])
        ).toEqual([0, 1, 2]);
      });
    });
  });

  describe('mapCorrectAnswers', () => {
    describe('for a single correct answer index', () => {
      it('returns updated answers', () => {
        expect(
          mapCorrectAnswers(
            [
              { answer: 'Answer 1', correct: true },
              { answer: 'Answer 2', correct: false },
              { answer: 'Answer 3', correct: true },
            ],
            1
          )
        ).toEqual([
          { answer: 'Answer 1', correct: false },
          { answer: 'Answer 2', correct: true },
          { answer: 'Answer 3', correct: false },
        ]);
      });
    });

    describe('for an array of correct answers indices', () => {
      it('returns updated answers', () => {
        expect(
          mapCorrectAnswers(
            [
              { answer: 'Answer 1', correct: true },
              { answer: 'Answer 2', correct: false },
              { answer: 'Answer 3', correct: true },
            ],
            [1, 2]
          )
        ).toEqual([
          { answer: 'Answer 1', correct: false },
          { answer: 'Answer 2', correct: true },
          { answer: 'Answer 3', correct: true },
        ]);
      });
    });
  });

  describe('updateAnswersToQuestionType', () => {
    let answers;

    describe('when converting originally empty answers to true/false', () => {
      it('returns true/false answers', () => {
        expect(updateAnswersToQuestionType(AssessmentItemTypes.TRUE_FALSE, [])).toEqual([
          { answer: 'True', correct: true, order: 1 },
          { answer: 'False', correct: false, order: 2 },
        ]);
      });
    });

    describe('for originally single selection answers', () => {
      beforeEach(() => {
        answers = [
          { answer: 'Mayonnaise (I mean you can, but...)', correct: false, order: 1 },
          { answer: 'Peanut butter', correct: true, order: 2 },
          { answer: 'Jelly', correct: false, order: 3 },
        ];
      });

      describe('conversion to single selection', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to multiple selection', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.MULTIPLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to input question', () => {
        it('makes all answers correct', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.INPUT_QUESTION, answers)).toEqual([
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: true, order: 2 },
            { answer: 'Jelly', correct: true, order: 3 },
          ]);
        });
      });

      describe('conversion to true/false', () => {
        it('returns true/false answers only', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.TRUE_FALSE, answers)).toEqual([
            { answer: 'True', correct: true, order: 1 },
            { answer: 'False', correct: false, order: 2 },
          ]);
        });
      });
    });

    describe('for originally input question', () => {
      beforeEach(() => {
        answers = [
          { answer: '8', correct: true, order: 1 },
          { answer: '8.0', correct: true, order: 2 },
        ];
      });

      describe('conversion to input question', () => {
        it('returns the same answers', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.INPUT_QUESTION, answers)).toEqual(
            answers
          );
        });
      });

      describe('conversion to multiple selection', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.MULTIPLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to single selection', () => {
        it('keeps only first answer as correct', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
          ).toEqual([
            { answer: '8', correct: true, order: 1 },
            { answer: '8.0', correct: false, order: 2 },
          ]);
        });
      });

      describe('conversion to true/false', () => {
        it('returns true/false answers only', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.TRUE_FALSE, answers)).toEqual([
            { answer: 'True', correct: true, order: 1 },
            { answer: 'False', correct: false, order: 2 },
          ]);
        });
      });
    });

    describe('for originally true/false question', () => {
      beforeEach(() => {
        answers = [
          { answer: 'True', correct: false, order: 1 },
          { answer: 'False', correct: true, order: 2 },
        ];
      });

      describe('conversion to true/false question', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to multiple selection', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.MULTIPLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to single selection', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to input question', () => {
        it('makes all answers correct', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.INPUT_QUESTION, answers)).toEqual([
            { answer: 'True', correct: true, order: 1 },
            { answer: 'False', correct: true, order: 2 },
          ]);
        });
      });
    });

    describe('for originally multiple selection answers', () => {
      describe('conversion to multiple selection', () => {
        it('returns the same answers', () => {
          expect(
            updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
          ).toEqual(answers);
        });
      });

      describe('conversion to single selection', () => {
        describe('if there are some correct answers', () => {
          beforeEach(() => {
            answers = [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: false, order: 1 },
              { answer: 'Peanut butter', correct: true, order: 2 },
              { answer: 'Jelly', correct: true, order: 3 },
            ];
          });

          it('keeps only first correct answer', () => {
            expect(
              updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
            ).toEqual([
              { answer: 'Mayonnaise (I mean you can, but...)', correct: false, order: 1 },
              { answer: 'Peanut butter', correct: true, order: 2 },
              { answer: 'Jelly', correct: false, order: 3 },
            ]);
          });
        });

        describe('if there is no correct answer', () => {
          beforeEach(() => {
            answers = [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: false, order: 1 },
              { answer: 'Peanut butter', correct: false, order: 2 },
              { answer: 'Jelly', correct: false, order: 3 },
            ];
          });

          it('makes a first answer correct', () => {
            expect(
              updateAnswersToQuestionType(AssessmentItemTypes.SINGLE_SELECTION, answers)
            ).toEqual([
              { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
              { answer: 'Peanut butter', correct: false, order: 2 },
              { answer: 'Jelly', correct: false, order: 3 },
            ]);
          });
        });
      });

      describe('conversion to input question', () => {
        beforeEach(() => {
          answers = [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: false, order: 2 },
            { answer: 'Jelly', correct: true, order: 3 },
          ];
        });

        it('marks all answers to be correct', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.INPUT_QUESTION, answers)).toEqual([
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: true, order: 2 },
            { answer: 'Jelly', correct: true, order: 3 },
          ]);
        });
      });

      describe('conversion to true/false', () => {
        beforeEach(() => {
          answers = [
            { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
            { answer: 'Peanut butter', correct: false, order: 2 },
            { answer: 'Jelly', correct: true, order: 3 },
          ];
        });

        it('returns true/false answers only', () => {
          expect(updateAnswersToQuestionType(AssessmentItemTypes.TRUE_FALSE, answers)).toEqual([
            { answer: 'True', correct: true, order: 1 },
            { answer: 'False', correct: false, order: 2 },
          ]);
        });
      });
    });
  });
});
