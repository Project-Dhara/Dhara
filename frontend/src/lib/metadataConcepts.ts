import {
  emptyNmdsFields,
  isNmdsFieldsComplete,
  mergeNmdsConcepts,
  nmdsFieldsToList,
  NMDS_CONCEPT_TEMPLATE,
  NMDS_TOPICS,
} from './nmdsConcepts'
import {
  emptySdgFields,
  isSdgFieldsComplete,
  mergeSdgConcepts,
  SDG_CONCEPT_TEMPLATE,
  SDG_FIELD_PLACEHOLDERS,
  SDG_METADATA_COLUMNS,
  SDG_TOPICS,
  sdgFieldsToList,
} from './sdgConcepts'
import { getMetadataStandard, type MetadataStandard } from './settingsConfig'

export function getConceptStandardConfig(standard?: MetadataStandard) {
  const resolved = standard || getMetadataStandard()
  if (resolved === 'sdg') {
    return {
      standard: 'sdg' as const,
      shortName: 'SDG',
      label: 'Sustainable Development Goals',
      topics: SDG_TOPICS,
      template: SDG_CONCEPT_TEMPLATE,
      placeholders: SDG_FIELD_PLACEHOLDERS,
      emptyFields: emptySdgFields,
      isComplete: isSdgFieldsComplete,
      fieldsToList: sdgFieldsToList,
      mergeConcepts: mergeSdgConcepts,
      knownConcepts: new Set(SDG_CONCEPT_TEMPLATE.filter((r) => !r.section).map((r) => r.concept)),
      sheetColumns: SDG_METADATA_COLUMNS,
      usesSdgSheet: true,
    }
  }
  return {
    standard: 'nmds' as const,
    shortName: 'NMDS',
    label: 'NMDS',
    topics: NMDS_TOPICS,
    template: NMDS_CONCEPT_TEMPLATE,
    placeholders: {},
    emptyFields: emptyNmdsFields,
    isComplete: isNmdsFieldsComplete,
    fieldsToList: nmdsFieldsToList,
    mergeConcepts: mergeNmdsConcepts,
    knownConcepts: new Set(NMDS_CONCEPT_TEMPLATE.filter((r) => !r.section).map((r) => r.concept)),
    sheetColumns: null,
    usesSdgSheet: false,
  }
}
