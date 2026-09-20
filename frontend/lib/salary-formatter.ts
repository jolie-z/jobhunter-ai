/**
 * BOSS Zhipin salary normalization utilities
 * 
 * Handles conversion between user input and BOSS standard format:
 * - User selection: "15k", "20k" (from dropdown options)
 * - Display format: "15k-25k" or "15-25K"
 * - Special case: "面议" (negotiable) → empty string
 */

/**
 * Normalize a single salary value to BOSS-standard k notation
 * @param input - Raw user input (e.g., "15k", "15", "面议")
 * @returns "15k" for valid, "" for invalid/negotiable
 */
export function normalizeSingleSalary(input: string | null): string {
  if (!input || typeof input !== 'string') return ''
  
  // Handle special case: negotiable salary
  const trimmed = input.trim()
  if (trimmed === '面议') return ''
  
  // Extract numeric value
  const cleaned = trimmed.replace(/[kK,,\s]/g, '').replace(/[\uff1c\uff1d]/g, '')
  const num = parseFloat(cleaned)
  
  // Check if it's a valid number > 0
  if (isNaN(num) || num <= 0) return ''
  
  // Convert to k notation (e.g., 15000 → 15k)
  const hasK = /[kK]/.test(trimmed)
  if (hasK || num < 1000) {
    return `${Math.round(num)}k`
  } else {
    return `${Math.round(num).toString()}`
  }
}

/**
 * Format complete salary range from min and max values
 * @param minSalary - Minimum salary (e.g., "15k", "面议", "")
 * @param maxSalary - Maximum salary (e.g., "25k", "面议", "")
 * @returns "15k-25k" for valid range, "" if any part is invalid
 */
export function formatSalaryRange(minSalary: string, maxSalary: string): string {
  const minCleaned = normalizeSingleSalary(minSalary)
  const maxCleaned = normalizeSingleSalary(maxSalary)
  
  // Both must be valid numbers
  if (!minCleaned || !maxCleaned) return ''
  
  // Validate numeric values
  const minNum = parseFloat(minCleaned.replace(/[kK]/g, ''))
  const maxNum = parseFloat(maxCleaned.replace(/[kK]/g, ''))
  
  if (isNaN(minNum) || isNaN(maxNum) || minNum <= 0 || maxNum <= 0) return ''
  
  return `${minCleaned}-${maxCleaned}`
}

/**
 * Parse BOSS salary format back to components (for editing existing expectations)
 * @param bossSalary - Formatted string like "15k-25k" or "15-25K"
 * @returns {min, max} objects or null if invalid/negotiable
 */
export function parseBossSalaryFormat(bossSalary: string | null): {
  min: string | null
  max: string | null
} | null {
  if (!bossSalary || bossSalary === '面议' || bossSalary === '') {
    return null
  }
  
  // Split by hyphen variants
  const parts = bossSalary.split(/[-–—]|,/).map(p => p.trim()).filter(Boolean)
  
  if (parts.length === 0) return null
  
  if (parts.length === 1) {
    const normalized = normalizeSingleSalary(parts[0])
    return normalized ? { min: normalized, max: null } : null
  }
  
  if (parts.length >= 2) {
    const min = normalizeSingleSalary(parts[0])
    const max = normalizeSingleSalary(parts[1])
    if (min && max) {
      return { min, max }
    }
  }
  
  return null
}
