/**
 * Shared status-page copy for transitions between Console stages
 * (Excel / SQL / PDF). Visual shape matches the PDF processing page.
 */

export const STATUS_TRANSITIONS = {
  filesToPreview: {
    title: 'Preparing preview',
    subtitle: 'Extracting tables and matching them for review.',
    steps: [
      { key: 'extract', label: 'Extracting tables from your source' },
      { key: 'match', label: 'Matching tables to metadata tag files' },
      { key: 'validate', label: 'Checking Source Table ID / Title' },
    ],
  },
  previewToGrouping: {
    title: 'Preparing grouping',
    subtitle: 'Organising tables into dataset groups.',
    steps: [
      { key: 'apply', label: 'Applying table ID and title corrections' },
      { key: 'group', label: 'Building dataset groups' },
    ],
  },
  groupingToMetadata: {
    title: 'Preparing metadata',
    subtitle: 'Auto-filling catalogue fields for each group — this can take a moment.',
    steps: [
      { key: 'check', label: 'Checking that every table is in a group' },
      { key: 'fill', label: 'Auto-filling metadata from Know Your Dataset' },
      { key: 'open', label: 'Opening the metadata workspace' },
    ],
  },
  metadataToClassify: {
    title: 'Preparing classification',
    subtitle: 'Saving metadata and loading columns for harmonisation.',
    steps: [
      { key: 'push', label: 'Saving metadata to the catalogue' },
      { key: 'load', label: 'Loading columns for classification' },
    ],
  },
  classifyToPublish: {
    title: 'Preparing publication',
    subtitle: 'Finalising classifications and opening publish.',
    steps: [
      { key: 'save', label: 'Saving classifications and code maps' },
      { key: 'open', label: 'Opening publication' },
    ],
  },
}
