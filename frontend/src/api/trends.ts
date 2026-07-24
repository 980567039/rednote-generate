import axios from 'axios'
import { API_BASE_URL } from './client'
import type { TrendsResponse } from './types'

export async function getTrends(): Promise<TrendsResponse> {
  const response = await axios.get<TrendsResponse>(`${API_BASE_URL}/trends`)
  return response.data
}
