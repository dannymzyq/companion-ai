import SwiftUI

@main
struct CompanionApp: App {
    init() {
        #if DEBUG || PRUEBAS
        DebugKeys.importFromEnvironment()
        #endif
    }

    var body: some Scene {
        WindowGroup {
            CompanionView()
                .ignoresSafeArea()
                .background(Color.black)
                .preferredColorScheme(.dark)
        }
    }
}
