import each from 'jest-each';

import { AssessmentItemTypes, ValidationErrors } from '../constants';
import {
  translateValidator,
  getTitleValidators,
  validateNodeTitle,
  validateNodeLicense,
  validateNodeCopyrightHolder,
  validateNodeLicenseDescription,
  validateNodeMasteryModel,
  validateNodeMasteryModelM,
  validateNodeMasteryModelN,
  isNodeComplete,
  validateNodeDetails,
  validateNodeFiles,
  sanitizeAssessmentItemAnswers,
  sanitizeAssessmentItemHints,
  sanitizeAssessmentItem,
  validateAssessmentItem,
} from './validation';
import { MasteryModelsNames } from 'shared/leUtils/MasteryModels';
import { ContentKindsNames } from 'shared/leUtils/ContentKinds';

describe('channelEdit utils', () => {
  describe('translateValidator', () => {
    it('returns true if a validator function returns true for a value', () => {
      const title = 'Title';
      expect(translateValidator(getTitleValidators()[0])(title)).toBe(true);
    });

    it('returns an error message if a validator function returns an error code for a value', () => {
      const title = '';
      expect(translateValidator(getTitleValidators()[0])(title)).toBe('Title is required');
    });
  });

  describe('validateNodeTitle', () => {
    it('returns no errors for a non-empty title', () => {
      const node = { title: 'title' };
      expect(validateNodeTitle(node)).toEqual([]);
    });

    it('returns an error for an empty title', () => {
      const node = { title: '' };
      expect(validateNodeTitle(node)).toEqual([ValidationErrors.TITLE_REQUIRED]);
    });

    it('returns an error for a whitespace title', () => {
      const node = { title: '  ' };
      expect(validateNodeTitle(node)).toEqual([ValidationErrors.TITLE_REQUIRED]);
    });
  });

  describe('validateNodeLicense', () => {
    it('returns no errors for a supported license', () => {
      // see shared/leUtils/Licenses
      const node = { license: { id: 1 } };
      expect(validateNodeLicense(node)).toEqual([]);
    });

    it('returns an error for an empty license', () => {
      const node = { license: null };
      expect(validateNodeLicense(node)).toEqual([ValidationErrors.LICENSE_REQUIRED]);
    });

    it('returns an error for an unsupported license', () => {
      // see shared/leUtils/Licenses
      const node = { license: { id: 10 } };
      expect(validateNodeLicense(node)).toEqual([ValidationErrors.LICENSE_REQUIRED]);
    });
  });

  describe('validateNodeCopyrightHolder', () => {
    it(`returns no errors for an empty copyright holder
      when no license is specified`, () => {
      const node = { copyright_holder: '' };
      expect(validateNodeCopyrightHolder(node)).toEqual([]);
    });

    it(`returns no errors for an empty copyright holder
      when a copyright holder is not required`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 8, copyright_holder_required: false },
        copyright_holder: '',
      };
      expect(validateNodeCopyrightHolder(node)).toEqual([]);
    });

    it(`returns an error for an empty copyright holder
      when a copyright holder is required`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 1, copyright_holder_required: true },
        copyright_holder: '',
      };
      expect(validateNodeCopyrightHolder(node)).toEqual([
        ValidationErrors.COPYRIGHT_HOLDER_REQUIRED,
      ]);
    });

    it(`returns an error for a whitespace copyright holder
      when a copyright holder is required`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 1, copyright_holder_required: true },
        copyright_holder: ' ',
      };
      expect(validateNodeCopyrightHolder(node)).toEqual([
        ValidationErrors.COPYRIGHT_HOLDER_REQUIRED,
      ]);
    });

    it(`returns no errors for a non-empty copyright holder
      when a copyright holder is required`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 1, copyright_holder_required: true },
        copyright_holder: 'Copyright holder',
      };
      expect(validateNodeCopyrightHolder(node)).toEqual([]);
    });
  });

  describe('validateNodeLicenseDescription', () => {
    it(`returns no errors for an empty license description
      when no license is specified`, () => {
      const node = { license_description: '' };
      expect(validateNodeLicenseDescription(node)).toEqual([]);
    });

    it(`returns no errors for an empty license description
      when a license is not custom`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 1, is_custom: false },
        license_description: '',
      };
      expect(validateNodeLicenseDescription(node)).toEqual([]);
    });

    it(`returns an error for an empty license description
      when a license is custom`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 9, is_custom: true },
        license_description: '',
      };
      expect(validateNodeLicenseDescription(node)).toEqual([
        ValidationErrors.LICENSE_DESCRIPTION_REQUIRED,
      ]);
    });

    it(`returns an error for a whitespace license description
      when a license is custom`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 9, is_custom: true },
        license_description: ' ',
      };
      expect(validateNodeLicenseDescription(node)).toEqual([
        ValidationErrors.LICENSE_DESCRIPTION_REQUIRED,
      ]);
    });

    it(`returns no errors for a non-empty license description
      when a license is custom`, () => {
      // see shared/leUtils/Licenses
      const node = {
        license: { id: 9, is_custom: true },
        license_description: 'License description',
      };
      expect(validateNodeLicenseDescription(node)).toEqual([]);
    });
  });

  describe('validateNodeMasteryModel', () => {
    it('returns an error for an empty mastery model', () => {
      const node = { extra_fields: null };
      expect(validateNodeMasteryModel(node)).toEqual([ValidationErrors.MASTERY_MODEL_REQUIRED]);
    });

    it('returns no errors when a mastery model specified', () => {
      const node = { extra_fields: { type: MasteryModelsNames.DO_ALL } };
      expect(validateNodeMasteryModel(node)).toEqual([]);
    });
  });

  describe('validateNodeMasteryModelM', () => {
    it(`returns no errors for empty m value
      when no mastery model is specified`, () => {
      const node = { extra_fields: { type: null, m: null } };
      expect(validateNodeMasteryModelM(node)).toEqual([]);
    });

    it(`returns no errors for empty m value
      for mastery models other than m of n`, () => {
      const node = { extra_fields: { type: MasteryModelsNames.DO_ALL, m: null } };
      expect(validateNodeMasteryModelM(node)).toEqual([]);
    });

    describe('for a mastery model m of n', () => {
      let node;
      beforeEach(() => {
        node = { extra_fields: { type: MasteryModelsNames.M_OF_N } };
      });

      it('returns errors for empty m value', () => {
        node.extra_fields.m = undefined;
        node.extra_fields.n = 3;

        expect(validateNodeMasteryModelM(node)).toEqual([
          ValidationErrors.MASTERY_MODEL_M_REQUIRED,
          ValidationErrors.MASTERY_MODEL_M_WHOLE_NUMBER,
          ValidationErrors.MASTERY_MODEL_M_GT_ZERO,
          ValidationErrors.MASTERY_MODEL_M_LTE_N,
        ]);
      });

      it('returns an error for non-integer m value', () => {
        node.extra_fields.m = 1.27;
        node.extra_fields.n = 3;

        expect(validateNodeMasteryModelM(node)).toEqual([
          ValidationErrors.MASTERY_MODEL_M_WHOLE_NUMBER,
        ]);
      });

      it('returns an error for m value smaller than zero', () => {
        node.extra_fields.m = -2;
        node.extra_fields.n = 3;

        expect(validateNodeMasteryModelM(node)).toEqual([ValidationErrors.MASTERY_MODEL_M_GT_ZERO]);
      });

      it('returns an error for m value larger than n value', () => {
        node.extra_fields.m = 4;
        node.extra_fields.n = 3;

        expect(validateNodeMasteryModelM(node)).toEqual([ValidationErrors.MASTERY_MODEL_M_LTE_N]);
      });

      it('returns no errors for m whole number smaller than n value', () => {
        node.extra_fields.m = 3;
        node.extra_fields.n = 4;

        expect(validateNodeMasteryModelM(node)).toEqual([]);
      });
    });
  });

  describe('validateNodeMasteryModelN', () => {
    it(`returns no errors for empty n value
      when no mastery model is specified`, () => {
      const node = { extra_fields: { type: null, n: null } };
      expect(validateNodeMasteryModelN(node)).toEqual([]);
    });

    it(`returns no errors for empty n value
      for mastery models other than m of n`, () => {
      const node = { extra_fields: { type: MasteryModelsNames.DO_ALL, n: null } };
      expect(validateNodeMasteryModelN(node)).toEqual([]);
    });

    describe('for a mastery model m of n', () => {
      let node;
      beforeEach(() => {
        node = { extra_fields: { type: MasteryModelsNames.M_OF_N } };
      });

      it('returns errors for empty n value', () => {
        node.extra_fields.n = undefined;

        expect(validateNodeMasteryModelN(node)).toEqual([
          ValidationErrors.MASTERY_MODEL_N_REQUIRED,
          ValidationErrors.MASTERY_MODEL_N_WHOLE_NUMBER,
          ValidationErrors.MASTERY_MODEL_N_GT_ZERO,
        ]);
      });

      it('returns an error for non-integer n value', () => {
        node.extra_fields.n = 1.27;

        expect(validateNodeMasteryModelN(node)).toEqual([
          ValidationErrors.MASTERY_MODEL_N_WHOLE_NUMBER,
        ]);
      });

      it('returns an error for n value smaller than zero', () => {
        node.extra_fields.n = -2;

        expect(validateNodeMasteryModelN(node)).toEqual([ValidationErrors.MASTERY_MODEL_N_GT_ZERO]);
      });

      it('returns no errors for n whole number', () => {
        node.extra_fields.n = 3;

        expect(validateNodeMasteryModelN(node)).toEqual([]);
      });
    });
  });

  describe('isNodeComplete', () => {
    it('returns false if node details are not valid', () => {
      const nodeDetails = {
        title: '',
        kind: ContentKindsNames.DOCUMENT,
        license: { id: 8 },
      };
      expect(isNodeComplete({ nodeDetails })).toBe(false);
    });

    describe('for a node other than exercise', () => {
      it('returns true if node details are valid', () => {
        const nodeDetails = {
          title: 'Node title',
          kind: ContentKindsNames.DOCUMENT,
          license: { id: 8 },
        };
        expect(isNodeComplete({ nodeDetails })).toBe(true);
      });
    });

    describe('for a node other than exercise and topic', () => {
      let nodeDetails;
      beforeEach(() => {
        nodeDetails = {
          title: 'Node title',
          kind: ContentKindsNames.DOCUMENT,
          license: { id: 8 },
        };
      });

      it('returns true if node details and all files are valid', () => {
        const files = [
          {
            id: 'file-id',
            error: undefined,
            preset: {
              supplementary: false,
            },
          },
        ];
        expect(isNodeComplete({ nodeDetails, files })).toBe(true);
      });

      it('returns false if files are not valid', () => {
        const files = [
          {
            id: 'file-id',
            error: 'error',
          },
        ];
        expect(isNodeComplete({ nodeDetails, files })).toBe(false);
      });
    });

    describe('for an exercise', () => {
      let nodeDetails;
      beforeEach(() => {
        nodeDetails = {
          title: 'Exercise',
          kind: ContentKindsNames.EXERCISE,
          license: { id: 8 },
          extra_fields: {
            type: 'do_all',
          },
        };
      });

      it('returns false if there are no assessment items', () => {
        const assessmentItems = [];
        expect(isNodeComplete({ nodeDetails, assessmentItems })).toBe(false);
      });

      it('returns false if there is an invalid assessment item', () => {
        const assessmentItems = [
          {
            question: 'Valid question',
            type: AssessmentItemTypes.SINGLE_SELECTION,
            answers: [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
              { answer: 'Peanut butter', correct: false, order: 2 },
            ],
          },
          {
            question: 'Invalid question (missing answers)',
            type: AssessmentItemTypes.SINGLE_SELECTION,
            answers: [],
          },
        ];
        expect(isNodeComplete({ nodeDetails, assessmentItems })).toBe(false);
      });

      it(`returns true if there is at least one assessment items
        and all assessment items are valid`, () => {
        const assessmentItems = [
          {
            question: 'Valid question',
            type: AssessmentItemTypes.SINGLE_SELECTION,
            answers: [
              { answer: 'Mayonnaise (I mean you can, but...)', correct: true, order: 1 },
              { answer: 'Peanut butter', correct: false, order: 2 },
            ],
          },
        ];
        expect(isNodeComplete({ nodeDetails, assessmentItems })).toBe(true);
      });
    });
  });

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
        [ValidationErrors.LICENSE_REQUIRED],
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
      // copyright holder is required for licenses other than Public Domain
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
        [ValidationErrors.LICENSE_DESCRIPTION_REQUIRED],
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
            type: 'do_all',
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
            type: 'm_of_n',
            m: 3,
          },
        },
        [
          ValidationErrors.MASTERY_MODEL_M_LTE_N,
          ValidationErrors.MASTERY_MODEL_N_REQUIRED,
          ValidationErrors.MASTERY_MODEL_N_WHOLE_NUMBER,
          ValidationErrors.MASTERY_MODEL_N_GT_ZERO,
        ],
      ],
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
          extra_fields: {
            type: 'm_of_n',
            m: 3,
            n: 2,
          },
        },
        [ValidationErrors.MASTERY_MODEL_M_LTE_N],
      ],
      [
        {
          title: 'Title',
          kind: 'exercise',
          license: 8,
          extra_fields: {
            type: 'm_of_n',
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
});
