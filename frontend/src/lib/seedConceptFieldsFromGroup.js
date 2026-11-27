/** Reconstitute NMDS/SDG concept field map from a matchResult group. */
export function seedConceptFieldsFromGroup(group, emptyFields, mergeConcepts) {
  const base = emptyFields()
  const conceptMeta = group?.concept_metadata
  if (conceptMeta && typeof conceptMeta === 'object' && !Array.isArray(conceptMeta)) {
    for (const key of Object.keys(base)) {
      if (conceptMeta[key]) base[key] = String(conceptMeta[key])
    }
  }
  // SDG mode stores indicator fields directly on metadata for the sheet grid.
  for (const key of Object.keys(base)) {
    if (group?.metadata?.[key]) base[key] = String(group.metadata[key])
  }
  // batch-push / matchResult sync shape: { standard, concepts: [...] }
  const nmds = group?.nmds_concepts
  if (nmds && typeof nmds === 'object') {
    const concepts = nmds.concepts
    if (Array.isArray(concepts) && concepts.length) {
      return mergeConcepts(base, concepts)
    }
    if (concepts && typeof concepts === 'object' && !Array.isArray(concepts)) {
      for (const key of Object.keys(base)) {
        if (concepts[key] != null && String(concepts[key]).trim()) {
          base[key] = String(concepts[key])
        }
      }
    }
  }
  if (Array.isArray(group?.concepts) && group.concepts.length) {
    return mergeConcepts(base, group.concepts)
  }
  return base
}
