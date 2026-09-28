import { lazy, Suspense, type ReactNode } from 'react'
import { createHashRouter, RouterProvider, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toaster'
import { AppShell } from '@/components/layout/app-shell'
import { getToken } from '@/lib/token'
import { Skeleton } from '@/components/ui/skeleton'

const LoginPage = lazy(() => import('@/pages/login'))
const HomePage = lazy(() => import('@/pages/home'))
const VideosPage = lazy(() => import('@/pages/videos'))
const CreatorsPage = lazy(() => import('@/pages/creators'))
const BenchmarkPage = lazy(() => import('@/pages/benchmark'))
const DraftsPage = lazy(() => import('@/pages/drafts'))
const ChatPage = lazy(() => import('@/pages/chat'))
const PersonaPage = lazy(() => import('@/pages/persona'))
const PromptsPage = lazy(() => import('@/pages/prompts'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false }
  }
})

function RequireAuth({ children }: { children: ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return <>{children}</>
}

function Page({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<Skeleton className="h-40 w-full" />}>{children}</Suspense>
  )
}

const router = createHashRouter([
  {
    path: '/login',
    element: (
      <Page>
        <LoginPage />
      </Page>
    )
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/home" replace /> },
      { path: 'home', element: <Page><HomePage /></Page> },
      { path: 'videos', element: <Page><VideosPage /></Page> },
      { path: 'drafts', element: <Page><DraftsPage /></Page> },
      { path: 'benchmark', element: <Page><BenchmarkPage /></Page> },
      { path: 'creators', element: <Page><CreatorsPage /></Page> },
      { path: 'persona', element: <Page><PersonaPage /></Page> },
      { path: 'prompts', element: <Page><PromptsPage /></Page> },
      { path: 'chat', element: <Page><ChatPage /></Page> },
      { path: '*', element: <Navigate to="/home" replace /> }
    ]
  }
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <RouterProvider router={router} />
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
