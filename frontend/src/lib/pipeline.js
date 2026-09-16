/** Shared console/PDF pipeline contract (re-exports only — no behavior change). */
export {
  EMPTY_GROUP_METADATA,
  fillGroupMetadataForMatchResult,
  previewReviewStatus,
  tableCode,
  tablePickerLabel,
  baseTitle,
  buildGroupName,
} from './postPreview'

export { STATUS_TRANSITIONS } from './consoleStatusTransitions'

export { STAGE_DEFS, stageIndexForStep, StageSidebar } from '../components/console/ConsoleStages'
