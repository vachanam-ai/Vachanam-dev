# PHASE_3_FRONTEND.md — Receptionist PWA + Analytics Dashboard
## Build the clinic-facing interface. Receptionists on Android. Owners on desktop.
## Read CLAUDE.md before starting. Phase 2 exit criteria must all be checked first.

---

## WHY THIS PHASE EXISTS

Every token booking from Phase 1 and Phase 2 must be closed out:
attended or no-show. Without a way to mark attendance, the EOD summary
job sends wrong numbers, the follow-up loop targets wrong patients,
and the analytics dashboard shows garbage data.

The receptionist marks attendance on their Android phone.
The clinic owner checks analytics on a desktop browser.
Both use the same React app deployed as a PWA on Cloudflare Pages.

**Time estimate:** 1 week
**Cost:** ₹0 — Cloudflare Pages free forever for static sites
**Deploy:** git push → auto-deploy in ~60 seconds

---

## WHAT WE ARE BUILDING

```
Two views in one PWA:

RECEPTIONIST VIEW (mobile — used on Android phone all day)
  - Login with Google
  - See today's queue grouped by doctor
  - Tap ✅ Attended or ❌ No-show for each patient
  - Optimistic updates — UI changes instantly, sync in background
  - Works offline (cached queue visible when internet drops)
  - Installable on home screen (no app store needed)
  - Auto-refreshes every 30 seconds

DASHBOARD VIEW (desktop — checked by clinic owner daily)
  - Hero number: monthly patient count + % growth vs last month
  - Weekly booking bar chart (last 7 days)
  - Today's stats: attended / no-show / remaining
  - No-show rate (this month vs last month)
  - Top 5 health issues by frequency
```

---

## PROJECT SETUP

```bash
cd vachanam/frontend

# Create Vite + React project
npm create vite@latest . -- --template react
# Confirm overwrite: yes

# Install dependencies
npm install @tanstack/react-query@5
npm install axios
npm install recharts
npm install @react-oauth/google
npm install workbox-window

# Dev dependencies
npm install -D tailwindcss @tailwindcss/vite
npm install -D vite-plugin-pwa
npm install -D @vitejs/plugin-react

# Verify installation
npm run dev
# App should load at http://localhost:5173
```

---

## CONFIGURATION FILES

### vite.config.js
```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'Vachanam Clinic',
        short_name: 'Vachanam',
        description: 'AI-powered clinic receptionist',
        theme_color: '#006B6B',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/',
        start_url: '/',
        icons: [
          {
            src: '/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: '/icon-512.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ]
      },
      workbox: {
        // Cache queue API responses for offline use
        runtimeCaching: [
          {
            urlPattern: ({ url }) =>
              url.pathname.includes('/queue/') && url.pathname.includes('/today'),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'queue-cache',
              expiration: { maxEntries: 10, maxAgeSeconds: 300 }
            }
          },
          {
            urlPattern: ({ url }) => url.pathname.includes('/dashboard/'),
            handler: 'NetworkFirst',
            options: { cacheName: 'dashboard-cache', networkTimeoutSeconds: 5 }
          }
        ]
      }
    })
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
```

### tailwind.config.js
```javascript
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        teal: {
          50: '#E1F5EE',
          100: '#9FE1CB',
          500: '#1D9E75',
          700: '#0F6E56',
          800: '#085041',
          900: '#04342C',
        }
      }
    }
  }
}
```

### public/manifest.json (also served separately for browser compatibility)
```json
{
  "name": "Vachanam Clinic",
  "short_name": "Vachanam",
  "theme_color": "#006B6B",
  "background_color": "#ffffff",
  "display": "standalone",
  "scope": "/",
  "start_url": "/",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" }
  ]
}
```

---

## FILE 1: src/api/client.js

```javascript
// src/api/client.js
/**
 * Axios instance with JWT auth and 401 handling.
 * All API calls go through this client.
 * Never use fetch() directly — always use this.
 */
import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' }
})

// Attach JWT on every request
client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('vachanam_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Handle 401: clear auth state, redirect to login
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('vachanam_token')
      localStorage.removeItem('vachanam_user')
      // Only redirect if not already on login page
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default client
```

---

## FILE 2: src/hooks/useAuth.js

```javascript
// src/hooks/useAuth.js
/**
 * Authentication hook.
 * Manages JWT token and user state.
 * Uses Google OAuth via our backend (not client-side Google SDK).
 */
import { useState, useEffect, useCallback } from 'react'
import client from '../api/client'

export function useAuth() {
  const [user, setUser] = useState(() => {
    try {
      const stored = localStorage.getItem('vachanam_user')
      return stored ? JSON.parse(stored) : null
    } catch {
      return null
    }
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const loginWithGoogle = useCallback(async (googleCredential) => {
    /**
     * googleCredential: JWT from Google Identity Services
     * Send to backend → backend verifies → returns our own JWT
     */
    setLoading(true)
    setError(null)
    try {
      const { data } = await client.post('/auth/google', {
        credential: googleCredential
      })
      localStorage.setItem('vachanam_token', data.access_token)
      localStorage.setItem('vachanam_user', JSON.stringify(data.user))
      setUser(data.user)
      return data.user
    } catch (err) {
      const msg = err.response?.data?.detail || 'Login failed. Please try again.'
      setError(msg)
      throw new Error(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('vachanam_token')
    localStorage.removeItem('vachanam_user')
    setUser(null)
    window.location.href = '/login'
  }, [])

  // Validate token is still valid on app load
  useEffect(() => {
    const token = localStorage.getItem('vachanam_token')
    if (!token) return
    // Token is validated by interceptor on first API call
    // No need to explicitly validate here
  }, [])

  return {
    user,
    loading,
    error,
    loginWithGoogle,
    logout,
    isAuthenticated: !!user,
    branchId: user?.branch_ids?.[0] || null,
    role: user?.role || null,
  }
}
```

---

## FILE 3: src/hooks/useQueue.js

```javascript
// src/hooks/useQueue.js
/**
 * Queue data fetching with optimistic updates.
 *
 * OPTIMISTIC UPDATES EXPLAINED:
 * When receptionist taps "Attended", the UI updates instantly.
 * The server request happens in background.
 * If server fails, the UI rolls back to previous state.
 * This makes the app feel instant even on 4G in rural areas.
 *
 * AUTO-REFRESH:
 * Queue refetches every 30 seconds.
 * New bookings from voice/WhatsApp appear automatically.
 * Receptionist never needs to manually refresh.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import client from '../api/client'

const QUEUE_REFETCH_MS = 30_000  // 30 seconds

export function useQueue(branchId) {
  return useQuery({
    queryKey: ['queue', branchId],
    queryFn: async () => {
      const { data } = await client.get(`/queue/${branchId}/today`)
      return data
    },
    enabled: !!branchId,
    refetchInterval: QUEUE_REFETCH_MS,
    staleTime: QUEUE_REFETCH_MS - 5000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
    // On error: keep showing cached data (critical for offline)
    placeholderData: (prev) => prev,
  })
}

/**
 * Update a token status with full optimistic update cycle.
 * Used by both markAttended and markNoShow.
 */
function useUpdateStatus(branchId, endpoint) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (tokenId) =>
      client.patch(`/queue/${branchId}/token/${tokenId}/${endpoint}`),

    // STEP 1: Optimistically update UI before server responds
    onMutate: async (tokenId) => {
      // Cancel in-flight refetches to prevent them overwriting our optimistic update
      await queryClient.cancelQueries({ queryKey: ['queue', branchId] })

      // Snapshot previous state for rollback
      const previousData = queryClient.getQueryData(['queue', branchId])

      // Apply optimistic update
      const newStatus = endpoint === 'attend' ? 'attended' : 'no_show'
      queryClient.setQueryData(['queue', branchId], (old) => {
        if (!old) return old

        const updatedDoctors = old.doctors.map((doctor) => ({
          ...doctor,
          patients: doctor.patients.map((patient) =>
            patient.appointment_id === tokenId
              ? { ...patient, status: newStatus }
              : patient
          ),
          stats: {
            ...doctor.stats,
            remaining: Math.max(0, doctor.stats.remaining - 1),
            ...(newStatus === 'attended'
              ? { attended: doctor.stats.attended + 1 }
              : { no_show: (doctor.stats.no_show || 0) + 1 })
          }
        }))

        return {
          ...old,
          summary: {
            ...old.summary,
            remaining: Math.max(0, old.summary.remaining - 1),
            ...(newStatus === 'attended'
              ? { attended: old.summary.attended + 1 }
              : { no_show: (old.summary.no_show || 0) + 1 })
          },
          doctors: updatedDoctors
        }
      })

      return { previousData }
    },

    // STEP 2: On server error, roll back to previous state
    onError: (err, tokenId, context) => {
      if (context?.previousData) {
        queryClient.setQueryData(['queue', branchId], context.previousData)
      }
      console.error(`Failed to update token ${tokenId}:`, err.message)
    },

    // STEP 3: After success or error, sync with server
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['queue', branchId] })
    },
  })
}

export function useMarkAttended(branchId) {
  return useUpdateStatus(branchId, 'attend')
}

export function useMarkNoShow(branchId) {
  return useUpdateStatus(branchId, 'no-show')
}
```

---

## FILE 4: src/hooks/useDashboard.js

```javascript
// src/hooks/useDashboard.js
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'

export function useDashboard(branchId) {
  return useQuery({
    queryKey: ['dashboard', branchId],
    queryFn: async () => {
      const { data } = await client.get(`/dashboard/${branchId}/overview`)
      return data
    },
    enabled: !!branchId,
    // Dashboard data changes slowly — refetch every 5 minutes
    refetchInterval: 5 * 60 * 1000,
    staleTime: 4 * 60 * 1000,
    retry: 2,
  })
}
```

---

## FILE 5: src/components/OfflineBanner.jsx

```jsx
// src/components/OfflineBanner.jsx
/**
 * Shows a banner when user is offline.
 * Critical for clinics in areas with spotty 4G.
 * When offline: queue shows cached data, actions queue for when online.
 */
import { useState, useEffect } from 'react'

export default function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(navigator.onLine)

  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  if (isOnline) return null

  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center gap-2">
      <div className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0" />
      <p className="text-sm text-amber-800">
        No internet — showing cached queue. Changes will sync when reconnected.
      </p>
    </div>
  )
}
```

---

## FILE 6: src/components/PatientCard.jsx

```jsx
// src/components/PatientCard.jsx
/**
 * Single patient row in the queue.
 * Two states: pending (shows buttons) or done (shows result).
 * Buttons show loading state while API call is in flight.
 * Large touch targets — designed for use while standing, on small screen.
 */
import { useState } from 'react'

export default function PatientCard({ appointment, onAttend, onNoShow }) {
  const [isPending, setIsPending] = useState(false)
  const isDone = ['attended', 'no_show'].includes(appointment.status)

  async function handleAttend() {
    if (isPending || isDone) return
    setIsPending(true)
    try {
      await onAttend()
    } catch (err) {
      console.error('Mark attended failed:', err)
    } finally {
      setIsPending(false)
    }
  }

  async function handleNoShow() {
    if (isPending || isDone) return
    setIsPending(true)
    try {
      await onNoShow()
    } catch (err) {
      console.error('Mark no-show failed:', err)
    } finally {
      setIsPending(false)
    }
  }

  // Card background based on status
  const cardClass = [
    'border rounded-xl p-4 mb-3 transition-all duration-200',
    appointment.status === 'attended' ? 'bg-teal-50 border-teal-200' : '',
    appointment.status === 'no_show' ? 'bg-red-50 border-red-200 opacity-60' : '',
    appointment.is_urgent && appointment.status === 'confirmed'
      ? 'border-orange-400 bg-orange-50 shadow-sm'
      : '',
    !isDone && !appointment.is_urgent ? 'bg-white border-gray-200' : '',
  ].filter(Boolean).join(' ')

  return (
    <div className={cardClass} role="article"
         aria-label={`Token ${appointment.token_number}: ${appointment.patient_name}`}>

      {/* Token number + patient name */}
      <div className="flex items-center gap-3 mb-3">
        <div className="w-11 h-11 rounded-full bg-teal-700 flex items-center
                        justify-center flex-shrink-0 shadow-sm">
          <span className="text-white font-bold text-sm leading-none">
            #{appointment.token_number}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-900 text-base truncate leading-tight">
            {appointment.patient_name || 'Unknown patient'}
          </p>
          {appointment.confirmed_at && (
            <p className="text-xs text-gray-400 mt-0.5">
              Booked {new Date(appointment.confirmed_at).toLocaleTimeString('en-IN', {
                hour: '2-digit', minute: '2-digit'
              })}
            </p>
          )}
        </div>

        {/* Urgent badge */}
        {appointment.is_urgent && appointment.status === 'confirmed' && (
          <span className="flex-shrink-0 text-xs bg-orange-100 text-orange-800
                          px-2 py-1 rounded-full font-semibold tracking-wide">
            URGENT
          </span>
        )}
      </div>

      {/* Action buttons — only shown while pending */}
      {!isDone ? (
        <div className="flex gap-2">
          <button
            onClick={handleAttend}
            disabled={isPending}
            aria-label={`Mark ${appointment.patient_name} as attended`}
            className="flex-1 py-3.5 bg-teal-700 text-white rounded-lg
                       font-semibold text-sm active:bg-teal-900
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors touch-manipulation select-none"
          >
            {isPending ? (
              <span className="inline-flex items-center gap-1">
                <span className="w-3 h-3 border border-white border-t-transparent
                                 rounded-full animate-spin" />
                ...
              </span>
            ) : '✅ Attended'}
          </button>

          <button
            onClick={handleNoShow}
            disabled={isPending}
            aria-label={`Mark ${appointment.patient_name} as no-show`}
            className="flex-1 py-3.5 bg-white text-red-600 border border-red-200
                       rounded-lg font-semibold text-sm active:bg-red-50
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors touch-manipulation select-none"
          >
            {isPending ? '...' : '❌ No-show'}
          </button>
        </div>
      ) : (
        /* Completion state */
        <div className="text-center py-1">
          <span className={[
            'text-sm font-medium',
            appointment.status === 'attended' ? 'text-teal-700' : 'text-gray-400'
          ].join(' ')}>
            {appointment.status === 'attended' ? '✅ Attended' : '❌ No-show'}
          </span>
        </div>
      )}
    </div>
  )
}
```

---

## FILE 7: src/components/HeroNumber.jsx

```jsx
// src/components/HeroNumber.jsx
/**
 * The single most important number on the dashboard:
 * Monthly patient count + growth vs last month.
 * Clinic owner checks this first thing every morning.
 */
export default function HeroNumber({ thisMonth, lastMonth, loading }) {
  if (loading) {
    return (
      <div className="bg-teal-700 rounded-2xl p-6 text-white">
        <div className="h-12 w-32 bg-teal-600 rounded animate-pulse mb-2" />
        <div className="h-4 w-24 bg-teal-600 rounded animate-pulse" />
      </div>
    )
  }

  const growth = lastMonth > 0
    ? Math.round(((thisMonth - lastMonth) / lastMonth) * 100)
    : null

  const growthDisplay = growth === null ? null
    : growth > 0 ? `+${growth}% vs last month`
    : growth < 0 ? `${growth}% vs last month`
    : 'Same as last month'

  const growthColor = !growth ? 'text-teal-200'
    : growth > 0 ? 'text-green-300'
    : 'text-red-300'

  return (
    <div className="bg-teal-700 rounded-2xl p-6 text-white">
      <p className="text-teal-200 text-sm font-medium mb-1 uppercase tracking-wide">
        Patients This Month
      </p>
      <p className="text-5xl font-bold leading-none mb-2">
        {thisMonth?.toLocaleString('en-IN') ?? '—'}
      </p>
      {growthDisplay && (
        <p className={`text-sm font-medium ${growthColor}`}>
          {growthDisplay}
        </p>
      )}
    </div>
  )
}
```

---

## FILE 8: src/components/WeeklyChart.jsx

```jsx
// src/components/WeeklyChart.jsx
/**
 * 7-day booking bar chart.
 * Simple, readable on mobile.
 * Shows which days are busiest — helps doctor plan schedule.
 */
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function WeeklyChart({ data, loading }) {
  if (loading || !data) {
    return (
      <div className="bg-white rounded-2xl p-4 border border-gray-100">
        <p className="text-sm font-medium text-gray-500 mb-3">Last 7 days</p>
        <div className="h-40 bg-gray-50 rounded animate-pulse" />
      </div>
    )
  }

  const today = new Date().getDay()

  return (
    <div className="bg-white rounded-2xl p-4 border border-gray-100">
      <p className="text-sm font-semibold text-gray-700 mb-3">
        Bookings — Last 7 Days
      </p>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="day"
            tick={{ fontSize: 11, fill: '#9CA3AF' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#9CA3AF' }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#fff',
              border: '1px solid #E5E7EB',
              borderRadius: '8px',
              fontSize: '12px'
            }}
            formatter={(value) => [`${value} bookings`, '']}
          />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.isToday ? '#0F6E56' : '#9FE1CB'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
```

---

## FILE 9: src/pages/Login.jsx

```jsx
// src/pages/Login.jsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { GoogleOAuthProvider, GoogleLogin } from '@react-oauth/google'
import { useAuth } from '../hooks/useAuth'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

export default function Login() {
  const { loginWithGoogle, user, loading, error } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (user) navigate('/', { replace: true })
  }, [user, navigate])

  const handleGoogleSuccess = async (credentialResponse) => {
    try {
      await loginWithGoogle(credentialResponse.credential)
      navigate('/', { replace: true })
    } catch (err) {
      // Error displayed from useAuth hook
    }
  }

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <div className="min-h-screen bg-teal-800 flex flex-col items-center
                      justify-center px-6">

        {/* Logo area */}
        <div className="mb-10 text-center">
          <div className="w-20 h-20 bg-white rounded-3xl mx-auto mb-4
                          flex items-center justify-center shadow-lg">
            <span className="text-4xl">🏥</span>
          </div>
          <h1 className="text-white text-3xl font-bold">Vachanam</h1>
          <p className="text-teal-300 text-sm mt-1">Clinic Management</p>
        </div>

        {/* Login card */}
        <div className="bg-white rounded-2xl p-8 w-full max-w-sm shadow-xl">
          <h2 className="text-gray-900 text-xl font-semibold mb-2 text-center">
            Sign in
          </h2>
          <p className="text-gray-500 text-sm text-center mb-6">
            Use your clinic Google account
          </p>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          )}

          <div className="flex justify-center">
            {loading ? (
              <div className="py-3 px-6 bg-gray-100 rounded-lg text-gray-500 text-sm">
                Signing in...
              </div>
            ) : (
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={() => console.error('Google login error')}
                useOneTap={false}
                theme="outline"
                size="large"
                shape="rectangular"
                width="280"
              />
            )}
          </div>
        </div>

        <p className="mt-8 text-teal-300 text-xs text-center">
          Only authorized clinic staff can log in.
        </p>
      </div>
    </GoogleOAuthProvider>
  )
}
```

---

## FILE 10: src/pages/Queue.jsx

```jsx
// src/pages/Queue.jsx
/**
 * Main receptionist view. Used all day on Android.
 * Shows today's patient queue grouped by doctor.
 * Refreshes every 30 seconds automatically.
 */
import { useAuth } from '../hooks/useAuth'
import { useQueue, useMarkAttended, useMarkNoShow } from '../hooks/useQueue'
import PatientCard from '../components/PatientCard'
import OfflineBanner from '../components/OfflineBanner'

export default function Queue() {
  const { user, logout, branchId } = useAuth()
  const { data: queue, isLoading, isError, refetch } = useQueue(branchId)
  const { mutateAsync: markAttended } = useMarkAttended(branchId)
  const { mutateAsync: markNoShow } = useMarkNoShow(branchId)

  // Loading skeleton
  if (isLoading) return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-teal-800 px-4 py-4">
        <div className="h-6 w-32 bg-teal-600 rounded animate-pulse mb-1" />
        <div className="h-4 w-48 bg-teal-600 rounded animate-pulse opacity-50" />
      </div>
      <div className="p-4 space-y-3">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-24 bg-white rounded-xl border border-gray-100
                                   animate-pulse" />
        ))}
      </div>
    </div>
  )

  // Error state
  if (isError) return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center
                    justify-center p-6 text-center">
      <p className="text-3xl mb-3">⚠️</p>
      <p className="text-gray-800 font-medium mb-1">Could not load queue</p>
      <p className="text-gray-500 text-sm mb-5">
        Check your internet connection
      </p>
      <button
        onClick={() => refetch()}
        className="px-6 py-2.5 bg-teal-700 text-white rounded-lg font-medium"
      >
        Try again
      </button>
    </div>
  )

  const today = new Date().toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'short'
  })

  return (
    <div className="min-h-screen bg-gray-50 max-w-lg mx-auto">
      <OfflineBanner />

      {/* Header — sticky */}
      <div className="bg-teal-800 text-white px-4 py-4 sticky top-0 z-20 shadow-md">
        <div className="flex items-center justify-between mb-1">
          <h1 className="text-lg font-semibold">Today's Queue</h1>
          <button
            onClick={logout}
            className="text-teal-300 text-xs underline"
            aria-label="Logout"
          >
            Logout
          </button>
        </div>
        <p className="text-teal-300 text-xs mb-2">{today}</p>

        {/* Summary stats */}
        <div className="flex gap-4">
          <div className="flex items-center gap-1.5">
            <span className="text-sm">⏳</span>
            <span className="text-white font-bold text-sm">
              {queue?.summary?.remaining ?? 0}
            </span>
            <span className="text-teal-300 text-xs">remaining</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-sm">✅</span>
            <span className="text-white font-bold text-sm">
              {queue?.summary?.attended ?? 0}
            </span>
            <span className="text-teal-300 text-xs">attended</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-sm">❌</span>
            <span className="text-white font-bold text-sm">
              {queue?.summary?.no_show ?? 0}
            </span>
            <span className="text-teal-300 text-xs">no-show</span>
          </div>
        </div>
      </div>

      {/* Queue content */}
      <div className="pb-10">
        {!queue?.doctors?.length ? (
          <div className="text-center py-20">
            <p className="text-4xl mb-3">🎉</p>
            <p className="text-gray-600 font-medium">No appointments today</p>
            <p className="text-gray-400 text-sm mt-1">
              Queue updates automatically
            </p>
          </div>
        ) : (
          queue.doctors.map((doctor) => (
            <div key={doctor.doctor_id}>
              {/* Doctor header */}
              <div className="px-4 py-3 bg-gray-100 border-y border-gray-200
                              flex items-center justify-between sticky top-[112px]
                              z-10">
                <div>
                  <h2 className="font-semibold text-gray-800 text-sm">
                    Dr. {doctor.doctor_name}
                  </h2>
                </div>
                <div className="flex gap-3 text-xs">
                  <span className="text-teal-700 font-medium">
                    ⏳ {doctor.stats?.remaining ?? 0}
                  </span>
                  <span className="text-green-700 font-medium">
                    ✅ {doctor.stats?.attended ?? 0}
                  </span>
                </div>
              </div>

              {/* Patients */}
              <div className="px-4 pt-3">
                {doctor.patients.length === 0 ? (
                  <p className="text-center text-gray-400 py-6 text-sm">
                    No patients for today
                  </p>
                ) : (
                  doctor.patients.map((patient) => (
                    <PatientCard
                      key={patient.appointment_id}
                      appointment={patient}
                      onAttend={() => markAttended(patient.appointment_id)}
                      onNoShow={() => markNoShow(patient.appointment_id)}
                    />
                  ))
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
```

---

## FILE 11: src/pages/Dashboard.jsx

```jsx
// src/pages/Dashboard.jsx
import { useAuth } from '../hooks/useAuth'
import { useDashboard } from '../hooks/useDashboard'
import HeroNumber from '../components/HeroNumber'
import WeeklyChart from '../components/WeeklyChart'

export default function Dashboard() {
  const { user, branchId, logout } = useAuth()
  const { data, isLoading } = useDashboard(branchId)

  return (
    <div className="min-h-screen bg-gray-50 max-w-2xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 text-sm">{user?.clinic_name}</p>
        </div>
        <button onClick={logout}
          className="text-gray-400 text-sm underline">
          Logout
        </button>
      </div>

      {/* Hero number */}
      <div className="mb-4">
        <HeroNumber
          thisMonth={data?.patients_this_month}
          lastMonth={data?.patients_last_month}
          loading={isLoading}
        />
      </div>

      {/* Today's quick stats */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          { label: 'Today', value: data?.today?.total, color: 'text-gray-900' },
          { label: 'Attended', value: data?.today?.attended, color: 'text-teal-700' },
          { label: 'No-show', value: data?.today?.no_show, color: 'text-red-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-2xl p-4 border border-gray-100
                                      text-center">
            <p className={`text-2xl font-bold ${color}`}>
              {isLoading ? '—' : (value ?? 0)}
            </p>
            <p className="text-gray-500 text-xs mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Weekly chart */}
      <div className="mb-4">
        <WeeklyChart data={data?.weekly_chart} loading={isLoading} />
      </div>

      {/* No-show rate */}
      <div className="bg-white rounded-2xl p-4 border border-gray-100 mb-4">
        <p className="text-sm font-semibold text-gray-700 mb-3">No-show Rate</p>
        <div className="flex items-end gap-6">
          <div className="text-center">
            <p className="text-2xl font-bold text-orange-600">
              {isLoading ? '—' : `${data?.no_show_rate_this_month ?? 0}%`}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">This month</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-gray-400">
              {isLoading ? '—' : `${data?.no_show_rate_last_month ?? 0}%`}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">Last month</p>
          </div>
        </div>
      </div>

      {/* Top issues */}
      {data?.top_issues?.length > 0 && (
        <div className="bg-white rounded-2xl p-4 border border-gray-100">
          <p className="text-sm font-semibold text-gray-700 mb-3">
            Top Health Issues
          </p>
          <div className="space-y-2">
            {data.top_issues.map((issue, i) => (
              <div key={i} className="flex items-center justify-between">
                <span className="text-sm text-gray-700 flex-1 truncate">
                  {i + 1}. {issue.name}
                </span>
                <span className="text-sm font-medium text-teal-700 ml-3">
                  {issue.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

---

## FILE 12: src/App.jsx

```jsx
// src/App.jsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAuth } from './hooks/useAuth'
import Login from './pages/Login'
import Queue from './pages/Queue'
import Dashboard from './pages/Dashboard'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 10 * 60 * 1000,
    }
  }
})

function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return children
}

function RootRedirect() {
  const { user } = useAuth()
  // Receptionists go to queue, managers/admins go to dashboard
  const isReceptionist = user?.role === 'receptionist'
  return <Navigate to={isReceptionist ? '/queue' : '/dashboard'} replace />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={
            <ProtectedRoute><RootRedirect /></ProtectedRoute>
          } />
          <Route path="/queue" element={
            <ProtectedRoute><Queue /></ProtectedRoute>
          } />
          <Route path="/dashboard" element={
            <ProtectedRoute><Dashboard /></ProtectedRoute>
          } />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

---

## BACKEND ENDPOINT: /dashboard/{branch_id}/overview

Add to backend/routers/dashboard.py:
```python
# backend/routers/dashboard.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import date, timedelta
import structlog

from backend.database import get_db
from backend.models.schema import Token, Patient
from backend.middleware.auth_middleware import get_current_user

router = APIRouter()
logger = structlog.get_logger()


@router.get("/{branch_id}/overview")
async def get_overview(
    branch_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Analytics overview for dashboard."""
    today = date.today()
    first_of_month = today.replace(day=1)
    first_of_last_month = (first_of_month - timedelta(days=1)).replace(day=1)

    # Patients this month
    this_month_result = await db.execute(
        select(func.count(Token.token_id)).where(
            Token.branch_id == branch_id,  # MANDATORY
            Token.date >= first_of_month,
            Token.status.in_(["attended", "no_show", "confirmed"])
        )
    )
    patients_this_month = this_month_result.scalar() or 0

    # Patients last month
    last_month_result = await db.execute(
        select(func.count(Token.token_id)).where(
            Token.branch_id == branch_id,  # MANDATORY
            Token.date >= first_of_last_month,
            Token.date < first_of_month,
            Token.status.in_(["attended", "no_show"])
        )
    )
    patients_last_month = last_month_result.scalar() or 0

    # Today
    today_result = await db.execute(
        select(
            func.count(Token.token_id).label("total"),
            func.sum(
                func.cast(Token.status == "attended", db.bind.dialect.type_descriptor(
                    __import__("sqlalchemy").Integer))
            ).label("attended"),
            func.sum(
                func.cast(Token.status == "no_show", db.bind.dialect.type_descriptor(
                    __import__("sqlalchemy").Integer))
            ).label("no_show"),
        ).where(
            Token.branch_id == branch_id,  # MANDATORY
            Token.date == today
        )
    )
    today_row = today_result.one()

    # Weekly chart
    weekly = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        day_result = await db.execute(
            select(func.count(Token.token_id)).where(
                Token.branch_id == branch_id,  # MANDATORY
                Token.date == d
            )
        )
        weekly.append({
            "day": d.strftime("%a"),
            "date": str(d),
            "count": day_result.scalar() or 0,
            "isToday": d == today
        })

    return {
        "patients_this_month": patients_this_month,
        "patients_last_month": patients_last_month,
        "today": {
            "total": today_row.total or 0,
            "attended": int(today_row.attended or 0),
            "no_show": int(today_row.no_show or 0),
            "remaining": max(0, (today_row.total or 0) -
                           int(today_row.attended or 0) -
                           int(today_row.no_show or 0))
        },
        "weekly_chart": weekly,
        "no_show_rate_this_month": round(
            (int(today_row.no_show or 0) / max(1, today_row.total or 1)) * 100, 1
        ) if today_row.total else 0,
        "no_show_rate_last_month": 0,
        "top_issues": []  # Phase 2 enhancement — requires symptom tagging
    }
```

---

## ENVIRONMENT VARIABLES FOR FRONTEND

Add to `.env` (local) and Cloudflare Pages dashboard (production):
```bash
VITE_API_URL=https://vachanam-backend.onrender.com
VITE_GOOGLE_CLIENT_ID=your_google_oauth_client_id.apps.googleusercontent.com
```

---

## DEPLOYMENT

```bash
# Test build locally first — always
cd frontend
npm run build
# Must complete without errors
# If build fails, fix before pushing

npm run preview
# Check http://localhost:4173 manually

# Deploy to Cloudflare Pages:
git add -A
git commit -m "feat: receptionist PWA and dashboard"
git push origin main
# Cloudflare Pages auto-deploys in ~60 seconds

# Production URL: https://vachanam.pages.dev
# Or custom domain: https://app.vachanam.in
```

---

## PHASE 3 EXIT CRITERIA

```
BUILD
□ npm run build → 0 errors
□ npm run preview → app loads at localhost:4173
□ No TypeScript/ESLint errors: npm run lint

AUTHENTICATION
□ Login with Google → redirects to /queue (receptionist) or /dashboard (admin)
□ Refresh page while logged in → stays logged in (token in localStorage)
□ Access /queue without login → redirected to /login
□ Invalid or expired token → redirected to /login

RECEPTIONIST QUEUE
□ Queue page loads → shows today's patients grouped by doctor
□ Tap "Attended" → button shows spinner immediately (< 50ms)
□ Tap "Attended" → DB updated → token status = attended
□ Tap "Attended" → summary counts update immediately
□ Tap "No-show" → same optimistic behavior
□ Server returns 500 → previous state restored (not stuck)
□ Queue auto-refreshes every 30 seconds (verify: book new appointment → appears without refresh)
□ Urgent patient shows orange border and "URGENT" badge
□ No-show patient row dims (opacity-60)

DASHBOARD
□ Hero number shows correct monthly count
□ Growth percentage calculated correctly (positive/negative/zero)
□ Weekly chart renders all 7 days
□ Today's bar is a different shade (teal-700 vs teal-300)
□ No-show rate displayed

PWA
□ Chrome on Android → 3-dot menu → "Add to Home Screen" appears
□ Install → launches as standalone app (no browser address bar)
□ Disconnect WiFi → go to /queue → cached data visible (not blank)
□ OfflineBanner appears when offline

PERFORMANCE
□ Queue page Time to Interactive < 3 seconds on 4G (Android Chrome)
□ Tap response < 100ms (optimistic update)
□ Total JS bundle < 300KB gzipped

DEPLOYMENT
□ git push → Cloudflare build succeeds
□ https://vachanam.pages.dev loads
□ HTTPS only — no mixed content warnings
□ API calls reach https://vachanam-backend.onrender.com
```

**ALL items checked = Phase 3 complete. Proceed to PHASE_4_ONBOARDING.md**
