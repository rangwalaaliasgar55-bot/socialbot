import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route } from 'react-router-dom';
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AnimatedRoutes } from "@/components/AnimatedRoutes";
import { PageTransition } from "@/components/PageTransition";
import Index from "./pages/Index";
import NotFound from "./pages/NotFound";
import Dashboard from "./pages/Dashboard";
import Connections from "./pages/Connections";
import Report from "./pages/Report";
import Planner from "./pages/Planner";
import Engagement from "./pages/Engagement";
import { NavBar } from "./components/social/NavBar";
import { ChatWidget } from "./components/social/ChatWidget";

/**
 * Configure TanStack Query client with optimized defaults
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Data considered fresh for 1 minute
      staleTime: 60 * 1000,
      // Cache data for 5 minutes
      gcTime: 5 * 60 * 1000,
      // Retry failed requests once
      retry: 1,
      // Don't refetch on window focus by default
      refetchOnWindowFocus: false,
      // Don't refetch on reconnect by default
      refetchOnReconnect: false,
    },
    mutations: {
      // Retry failed mutations once
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <BrowserRouter>
          <NavBar />
          <AnimatedRoutes>
            <Route path="/" data-genie-title="Home Page" data-genie-key="Home" element={<PageTransition transition="slide-up"><Index /></PageTransition>} />
            <ChatWidget />
            {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
            <Route path="/dashboard" data-genie-title="Dashboard" data-genie-key="Dashboard" element={<PageTransition transition="slide-up"><Dashboard /></PageTransition>} />
            <Route path="/connections" data-genie-title="Connections" data-genie-key="Connections" element={<PageTransition transition="slide-up"><Connections /></PageTransition>} />
            <Route path="/report" data-genie-title="Report" data-genie-key="Report" element={<PageTransition transition="slide-up"><Report /></PageTransition>} />
            <Route path="/planner" data-genie-title="Planner" data-genie-key="Planner" element={<PageTransition transition="slide-up"><Planner /></PageTransition>} />
            <Route path="/engagement" data-genie-title="Engagement" data-genie-key="Engagement" element={<PageTransition transition="slide-up"><Engagement /></PageTransition>} />
            <Route path="*" data-genie-key="NotFound" data-genie-title="Not Found" element={<PageTransition transition="fade"><NotFound /></PageTransition>} />
          </AnimatedRoutes>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App
