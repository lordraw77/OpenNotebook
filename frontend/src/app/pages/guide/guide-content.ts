import { Lang } from '../../core/i18n';

/** One section of the user guide. `shot` is a file in public/guide/<lang>/ (captured by scripts/docs). */
export interface GuideSection {
  id: string;
  title: string;
  icon: string;
  intro: string[];
  steps?: string[];
  tips?: string[];
  shots?: { file: string; alt: string }[];
}

const EN: GuideSection[] = [
  {
    id: 'start',
    title: 'Getting started',
    icon: 'rocket_launch',
    intro: [
      'OpenNotebook answers questions using only the documents you give it, and every statement in an answer links to the passage it comes from. No model runs inside the application: an administrator connects external model providers once, and everybody benefits.',
    ],
    steps: [
      'Open the address your administrator gave you and sign in with your email and password (or with single sign-on, if offered).',
      'The top bar gives access to the main pages: Workbench (chat and sources), History, Upload, Wiki, RAG Status and Settings. On narrow screens the labels collapse into icons.',
      'Use the language button to switch between English and Italian and the sun button for the light, dark or system theme. The whole interface, including this guide, follows the language you choose.',
    ],
    shots: [
      { file: 'login', alt: 'The sign-in page' },
      { file: 'language-menu', alt: 'The language menu in the top bar' },
    ],
  },
  {
    id: 'organize',
    title: 'Organize your material',
    icon: 'account_tree',
    intro: [
      'Material is organized in a tree. A project is always a root; inside it you can nest workspaces and notebooks freely. Sources (documents) live in notebooks, but you can also upload to a project or workspace directly.',
      'The node you select in the tree is the scope of your questions: the chat and the search only use the active sources inside that node and everything below it.',
    ],
    steps: [
      'Click the folder button in the Sources column to create a project, then use the three-dot menu of a node to add a workspace or notebook, rename it, upload sources, share it or delete it.',
      'Use the switch next to a node or a source to include it in or exclude it from the search. An excluded node excludes everything inside it, which is handy to compare a subset of the material.',
      'Click the arrow to expand a node: notebooks list their sources, and the status icon next to a source shows whether it is still being indexed or failed.',
    ],
    shots: [
      { file: 'tree-menu', alt: 'The node menu of a project' },
      { file: 'workbench', alt: 'The Workbench with the tree expanded' },
    ],
  },
  {
    id: 'upload',
    title: 'Add sources',
    icon: 'upload_file',
    intro: [
      'Open Upload from the top bar (or from the node menu) and choose where the files go. Drop files on the dashed area or use Choose files; the type is detected from the content, not from the extension.',
      'Supported: PDF, DOCX, XLSX, PPTX, Markdown, text and HTML; source code in many languages; images (PNG, JPEG, WebP, TIFF, GIF) that are read with OCR and described by a vision model; and archives (ZIP, TAR, 7z and RAR) whose files each become a source that keeps its path.',
      'Pictures inside PDF and DOCX files are read too: their text and a short description are indexed at the place where the picture appears, and in a PDF a citation highlights the picture itself. Scanned PDF pages are transcribed with OCR, and when the vision model can locate text, a citation highlights the exact lines instead of the whole page. Both need an OCR or vision model (Settings → Models).',
    ],
    steps: [
      'Choose the destination project, workspace or notebook.',
      'Drop your files, or paste web addresses (one per line) in Add web pages. You can follow links one or two levels on the same site, up to a page limit.',
      'To follow a code repository, use Add a git repository: give the URL, the branch, an optional access token and how often it should synchronise. Only hosts allowed by the administrator can be used.',
      'Watch the table below: a source goes through queued, parsing, chunking and embedding before it is ready. A failed source shows the reason and can be retried.',
    ],
    tips: [
      'Encrypted archive members are skipped and reported in the source details. Archives and images inside archives are expanded up to a safe depth and size.',
      'A file already present in the notebook is recognised by its content and not added twice.',
    ],
    shots: [{ file: 'upload', alt: 'The Upload page' }],
  },
  {
    id: 'chat',
    title: 'Ask questions and read answers',
    icon: 'forum',
    intro: [
      'Select a project, workspace or notebook, type a question and press Ask. The answer streams in and uses only the active sources of the scope. Each numbered chip is a citation: it names the source and where in it the passage is (page, or lines for text and code).',
      'If the sources do not contain the answer, the assistant says so instead of guessing. Under an answer you may see a note when a sentence has no citation or a marker was removed because it pointed to a passage that was not provided.',
    ],
    steps: [
      'Pick the chat model in the top right if you do not want the default. If the first model fails, the next one in the chain answers and the answer is marked as a fallback.',
      'Follow-up questions such as "and the second?" are rewritten into a complete search query before searching.',
      'Use the copy button to copy an answer, or the note button to save it, with its citations, as a note in the notebook.',
      'Conversations are kept per scope: use the conversation menu to switch, rename, delete or start a new chat.',
    ],
    shots: [{ file: 'workbench', alt: 'A grounded answer with citations' }],
  },
  {
    id: 'viewer',
    title: 'Check a citation',
    icon: 'fact_check',
    intro: [
      'Click a citation chip to open the original document at the cited passage. PDFs open on the right page with the passage highlighted; text, Markdown and code open with the passage selected, with line numbers.',
      'When a passage spans several pages, the viewer lists them and lets you jump between them. Use the arrow at the top left to go back to the chat.',
    ],
    shots: [{ file: 'viewer', alt: 'The PDF viewer with the cited passage highlighted' }],
  },
  {
    id: 'details',
    title: 'Source details and summaries',
    icon: 'description',
    intro: [
      'Click a source in the tree, or the information button in the viewer, to see its details: status, size, pages, when it was indexed, a generated summary, suggested questions and the chunks it was split into.',
      'Click a suggested question to ask it in the chat. From here you can also download the original file, re-index the source or delete it (and for archives, see the files that were skipped and why; for git sources, synchronise now or change the schedule).',
    ],
    shots: [{ file: 'source-details', alt: 'Source details with summary and suggested questions' }],
  },
  {
    id: 'search',
    title: 'Search passages',
    icon: 'search',
    intro: [
      'Switch the center panel from Chat to Search to see the passages a query finds, with their score, without asking a model. It is the same hybrid search (meaning plus keywords, optionally re-ranked) that feeds the chat, so it is a quick way to check why an answer says what it says.',
    ],
    shots: [{ file: 'search', alt: 'The Search panel' }],
  },
  {
    id: 'research',
    title: 'Deep research',
    icon: 'travel_explore',
    intro: [
      'For complex questions, turn on Deep research before asking. The assistant splits the question into several searches, reads what it found, searches again for what is missing, and writes a structured report with citations. It is slower and uses more model calls, so use it when a plain answer is not enough.',
      'The report starts with a line such as "3 search steps, 7 passages": click it to see the searches that were made.',
    ],
    shots: [{ file: 'deep-research', alt: 'A deep research report' }],
  },
  {
    id: 'notes',
    title: 'Notes',
    icon: 'sticky_note_2',
    intro: [
      'The right column holds the notes of the selected notebook. Write a note in Markdown with New note, or save an answer as a note. Tick Index as source to make the note searchable: it then takes part in answers like any other source.',
    ],
    shots: [{ file: 'note-dialog', alt: 'The new note form' }],
  },
  {
    id: 'wiki',
    title: 'Knowledge graph and wiki',
    icon: 'hub',
    intro: [
      'After indexing, entities (products, components, concepts, functions, files) and the relations between them are extracted. The Wiki page shows them for the scope you choose: a graph view, and a page per entity with what the sources say about it, related entities and where it is mentioned.',
      'The graph also helps the chat: questions that need several connected facts find passages through related entities. Editors can fix the graph with Edit the graph: rename, merge duplicates, add or delete relations. Edits survive re-indexing.',
    ],
    steps: [
      'Choose the scope, optionally filter by entity type or search a name.',
      'Switch between Graph and Page; click an entity to open its page.',
      'Use Rewrite the page to have the page written again from the passages you can read.',
    ],
    shots: [
      { file: 'wiki-graph', alt: 'The knowledge graph' },
      { file: 'wiki-page', alt: 'The page of an entity' },
    ],
  },
  {
    id: 'history',
    title: 'Chat history',
    icon: 'history',
    intro: [
      'History lists all your conversations across scopes, grouped by date. Search inside the messages, filter by scope, open a conversation in its own scope, download it as Markdown or delete it.',
    ],
    shots: [{ file: 'history', alt: 'The chat history page' }],
  },
  {
    id: 'share',
    title: 'Sharing and permissions',
    icon: 'group',
    intro: [
      'Access is granted on a node and applies to everything inside it. Roles: Viewer (read and ask), Editor (also add and change sources and notes) and Owner (also share and delete). Open the node menu and choose Share, then pick a person or a group and a role.',
      'A project must always keep at least one owner. Groups are managed by administrators in Settings and can be kept in sync with single sign-on.',
    ],
    shots: [{ file: 'share-dialog', alt: 'The Share dialog' }],
  },
  {
    id: 'project',
    title: 'Project settings',
    icon: 'tune',
    intro: [
      "Project owners can open Project settings from the project menu. The provider policy chooses which model providers may receive the project's content (documents, questions, images): all configured providers, or only the ones you select, for example a single provider you trust for confidential material. With no provider selected, nothing can be indexed or answered in the project.",
      'The same dialog shows the search index and which embedding model currently serves the searches.',
    ],
    shots: [{ file: 'project-settings', alt: 'Project settings' }],
  },
  {
    id: 'models',
    title: 'Models and providers (administrators)',
    icon: 'settings',
    intro: [
      'In Settings → Providers an administrator adds the external providers (API key, optional base URL), syncs their model catalogs and enables the models to use. Keys are stored encrypted and never shown again. Use Test next to a model to check it works.',
      'In Settings → Models each phase gets a chain of models: chat, summaries, graph extraction, image description, OCR, embedding and optional re-ranking. The first model is used, the following ones are fallbacks. A project can override the global chain. Changing the embedding model requires re-indexing the sources.',
      'Settings → Users and Groups create accounts and groups; access itself is granted from the Workbench tree.',
    ],
    shots: [
      { file: 'settings-models', alt: 'Model chains per phase' },
      { file: 'settings-providers', alt: 'The providers list' },
    ],
  },
  {
    id: 'status',
    title: 'RAG Status',
    icon: 'monitor_heart',
    intro: [
      'RAG Status shows the health of the services, how many sources are in each state, the queues, the index per project (embedding model, sources, chunks) and the latest jobs. Failed sources are listed with the reason and a Retry button.',
      'Use Re-index when you change the embedding model (it calls the embedding provider for every chunk), and Rebuild graph to extract the knowledge graph again.',
    ],
    shots: [{ file: 'status', alt: 'The RAG Status page' }],
  },
  {
    id: 'help',
    title: 'Troubleshooting',
    icon: 'help',
    intro: ['Common situations and what to do.'],
    tips: [
      'A source stays failed with "needs an OCR or a vision model": ask an administrator to assign one in Settings → Models, then press Retry or Re-index.',
      'An answer says the information was not found: check that the sources are switched on, that the scope contains them and that they are ready; try the Search panel to see what is retrieved.',
      'Citations open the text viewer instead of the PDF: the file is a DOCX, XLSX or similar and no converter service is configured; the text is the same.',
      'Web pages that build their content with JavaScript yield little text; save the page as PDF and upload it instead.',
      'A deep research limit message means the hourly allowance is used up; wait and retry.',
    ],
  },
];

const IT: GuideSection[] = [
  {
    id: 'start',
    title: 'Per iniziare',
    icon: 'rocket_launch',
    intro: [
      "OpenNotebook risponde alle domande usando solo i documenti che gli fornisci, e ogni affermazione di una risposta rimanda al passaggio da cui proviene. Nessun modello gira dentro l'applicazione: un amministratore collega una volta i provider esterni di modelli e tutti ne beneficiano.",
    ],
    steps: [
      "Apri l'indirizzo che ti ha dato l'amministratore ed entra con email e password (o con il single sign-on, se disponibile).",
      'La barra in alto dà accesso alle pagine principali: Workbench (chat e fonti), Cronologia, Carica, Wiki, Stato RAG e Impostazioni. Sugli schermi stretti le etichette diventano icone.',
      "Il pulsante della lingua alterna italiano e inglese, quello con il sole il tema chiaro, scuro o di sistema. Tutta l'interfaccia, questa guida compresa, segue la lingua scelta.",
    ],
    shots: [
      { file: 'login', alt: 'La pagina di accesso' },
      { file: 'language-menu', alt: 'Il menu della lingua nella barra in alto' },
    ],
  },
  {
    id: 'organize',
    title: 'Organizza il materiale',
    icon: 'account_tree',
    intro: [
      'Il materiale è organizzato ad albero. Un progetto è sempre una radice; al suo interno puoi annidare liberamente workspace e notebook. Le fonti (documenti) stanno nei notebook, ma puoi caricarle anche direttamente in un progetto o in un workspace.',
      "Il nodo selezionato nell'albero è l'ambito delle tue domande: chat e ricerca usano solo le fonti attive dentro quel nodo e tutto ciò che contiene.",
    ],
    steps: [
      'Clicca il pulsante con la cartella nella colonna Fonti per creare un progetto, poi usa il menu a tre puntini di un nodo per aggiungere un workspace o un notebook, rinominarlo, caricare fonti, condividerlo o eliminarlo.',
      "L'interruttore accanto a un nodo o a una fonte la include o la esclude dalla ricerca. Un nodo escluso esclude tutto ciò che contiene, utile per confrontare solo una parte del materiale.",
      "Clicca la freccia per espandere un nodo: i notebook elencano le fonti e l'icona di stato accanto a una fonte indica se è ancora in indicizzazione o non è riuscita.",
    ],
    shots: [
      { file: 'tree-menu', alt: 'Il menu del nodo di un progetto' },
      { file: 'workbench', alt: "Il Workbench con l'albero espanso" },
    ],
  },
  {
    id: 'upload',
    title: 'Aggiungi fonti',
    icon: 'upload_file',
    intro: [
      "Apri Carica dalla barra in alto (o dal menu del nodo) e scegli dove vanno i file. Trascinali nell'area tratteggiata o usa Scegli i file; il tipo viene riconosciuto dal contenuto, non dall'estensione.",
      'Formati supportati: PDF, DOCX, XLSX, PPTX, Markdown, testo e HTML; codice sorgente in molti linguaggi; immagini (PNG, JPEG, WebP, TIFF, GIF) lette con OCR e descritte da un modello di visione; archivi (ZIP, TAR, 7z e RAR) i cui file diventano ciascuno una fonte che conserva il proprio percorso.',
      "Vengono lette anche le immagini dentro PDF e DOCX: il testo e una breve descrizione sono indicizzati nel punto in cui compare l'immagine e, in un PDF, una citazione evidenzia l'immagine stessa. Le pagine PDF scansionate sono trascritte con OCR e, quando il modello di visione sa localizzare il testo, una citazione evidenzia le righe esatte invece dell'intera pagina. Entrambe le funzioni richiedono un modello OCR o di visione (Impostazioni → Modelli).",
    ],
    steps: [
      'Scegli il progetto, workspace o notebook di destinazione.',
      'Trascina i file, oppure incolla indirizzi web (uno per riga) in Aggiungi pagine web. Puoi seguire i link di uno o due livelli sullo stesso sito, fino a un limite di pagine.',
      "Per seguire un repository di codice usa Aggiungi un repository git: indica URL, ramo, un eventuale token di accesso e ogni quanto sincronizzare. Si possono usare solo gli host consentiti dall'amministratore.",
      'Guarda la tabella sotto: una fonte passa da in coda, analisi, suddivisione ed embedding prima di essere pronta. Una fonte non riuscita mostra il motivo e si può riprovare.',
    ],
    tips: [
      'I membri cifrati degli archivi vengono saltati e indicati nei dettagli della fonte. Archivi e immagini dentro gli archivi sono espansi fino a una profondità e dimensione sicure.',
      'Un file già presente nel notebook viene riconosciuto dal contenuto e non viene aggiunto due volte.',
    ],
    shots: [{ file: 'upload', alt: 'La pagina Carica' }],
  },
  {
    id: 'chat',
    title: 'Fai domande e leggi le risposte',
    icon: 'forum',
    intro: [
      "Seleziona un progetto, workspace o notebook, scrivi una domanda e premi Chiedi. La risposta arriva in streaming e usa solo le fonti attive dell'ambito. Ogni etichetta numerata è una citazione: indica la fonte e il punto in cui si trova il passaggio (pagina, oppure righe per testo e codice).",
      "Se le fonti non contengono la risposta, l'assistente lo dice invece di tirare a indovinare. Sotto una risposta può comparire un avviso se una frase non ha citazioni o se un riferimento è stato rimosso perché puntava a un passaggio non fornito.",
    ],
    steps: [
      'Scegli il modello di chat in alto a destra se non vuoi quello predefinito. Se il primo modello fallisce risponde il successivo della catena e la risposta è contrassegnata come «riserva».',
      'Le domande successive come «e la seconda?» vengono riscritte in una query completa prima della ricerca.',
      'Usa il pulsante di copia per copiare una risposta, o quello della nota per salvarla, con le citazioni, come nota del notebook.',
      "Le conversazioni sono conservate per ambito: dal menu della conversazione puoi passare a un'altra, rinominarla, eliminarla o iniziare una nuova chat.",
    ],
    shots: [{ file: 'workbench', alt: 'Una risposta fondata sulle fonti con le citazioni' }],
  },
  {
    id: 'viewer',
    title: 'Verifica una citazione',
    icon: 'fact_check',
    intro: [
      'Clicca su una citazione per aprire il documento originale nel passaggio citato. I PDF si aprono sulla pagina giusta con il passaggio evidenziato; testo, Markdown e codice si aprono con il passaggio selezionato e i numeri di riga.',
      "Quando un passaggio copre più pagine, il visualizzatore le elenca e permette di passare dall'una all'altra. Usa la freccia in alto a sinistra per tornare alla chat.",
    ],
    shots: [{ file: 'viewer', alt: 'Il visualizzatore PDF con il passaggio citato evidenziato' }],
  },
  {
    id: 'details',
    title: 'Dettagli e riassunti delle fonti',
    icon: 'description',
    intro: [
      "Clicca una fonte nell'albero, o il pulsante informazioni nel visualizzatore, per vederne i dettagli: stato, dimensione, pagine, data di indicizzazione, un riassunto generato, domande suggerite e i chunk in cui è stata suddivisa.",
      'Clicca una domanda suggerita per farla nella chat. Da qui puoi anche scaricare il file originale, re-indicizzare la fonte o eliminarla (per gli archivi vedi i file saltati e perché; per le fonti git puoi sincronizzare subito o cambiare la pianificazione).',
    ],
    shots: [
      { file: 'source-details', alt: 'Dettagli di una fonte con riassunto e domande suggerite' },
    ],
  },
  {
    id: 'search',
    title: 'Cerca nei passaggi',
    icon: 'search',
    intro: [
      'Passa il pannello centrale da Chat a Cerca per vedere i passaggi trovati da una ricerca, con il loro punteggio, senza interpellare un modello. È la stessa ricerca ibrida (significato più parole chiave, con eventuale riordino) che alimenta la chat: un modo rapido per capire perché una risposta dice quello che dice.',
    ],
    shots: [{ file: 'search', alt: 'Il pannello di ricerca' }],
  },
  {
    id: 'research',
    title: 'Ricerca approfondita',
    icon: 'travel_explore',
    intro: [
      "Per le domande complesse attiva Ricerca approfondita prima di chiedere. L'assistente divide la domanda in più ricerche, legge ciò che ha trovato, cerca di nuovo ciò che manca e scrive un report strutturato con citazioni. È più lenta e usa più chiamate ai modelli: usala quando una risposta semplice non basta.",
      'Il report inizia con una riga come «3 passi di ricerca, 7 passaggi»: cliccala per vedere le ricerche effettuate.',
    ],
    shots: [{ file: 'deep-research', alt: 'Un report di ricerca approfondita' }],
  },
  {
    id: 'notes',
    title: 'Note',
    icon: 'sticky_note_2',
    intro: [
      'La colonna di destra contiene le note del notebook selezionato. Scrivi una nota in Markdown con Nuova nota, oppure salva una risposta come nota. Spunta Indicizza come fonte per renderla ricercabile: parteciperà alle risposte come qualsiasi altra fonte.',
    ],
    shots: [{ file: 'note-dialog', alt: 'Il modulo di nuova nota' }],
  },
  {
    id: 'wiki',
    title: 'Knowledge graph e wiki',
    icon: 'hub',
    intro: [
      "Dopo l'indicizzazione vengono estratte le entità (prodotti, componenti, concetti, funzioni, file) e le relazioni tra loro. La pagina Wiki le mostra per l'ambito scelto: una vista a grafo e una pagina per ogni entità con ciò che dicono le fonti, le entità correlate e dove è citata.",
      'Il grafo aiuta anche la chat: le domande che richiedono più fatti collegati trovano passaggi tramite le entità correlate. Gli editor possono correggere il grafo con Modifica il grafo: rinominare, unire duplicati, aggiungere o eliminare relazioni. Le modifiche restano dopo una nuova indicizzazione.',
    ],
    steps: [
      "Scegli l'ambito, filtra se vuoi per tipo di entità o cerca un nome.",
      "Alterna Grafo e Pagina; clicca un'entità per aprirne la pagina.",
      'Usa Riscrivi la pagina per far scrivere di nuovo la pagina dai passaggi che puoi leggere.',
    ],
    shots: [
      { file: 'wiki-graph', alt: 'Il knowledge graph' },
      { file: 'wiki-page', alt: "La pagina di un'entità" },
    ],
  },
  {
    id: 'history',
    title: 'Cronologia delle chat',
    icon: 'history',
    intro: [
      'La Cronologia elenca tutte le tue conversazioni di ogni ambito, raggruppate per data. Cerca nei messaggi, filtra per ambito, apri una conversazione nel suo ambito, scaricala in Markdown o eliminala.',
    ],
    shots: [{ file: 'history', alt: 'La pagina della cronologia' }],
  },
  {
    id: 'share',
    title: 'Condivisione e permessi',
    icon: 'group',
    intro: [
      "L'accesso si concede su un nodo e vale per tutto ciò che contiene. Ruoli: Lettore (legge e fa domande), Editor (aggiunge e modifica anche fonti e note) e Proprietario (condivide ed elimina). Apri il menu del nodo, scegli Condividi, poi una persona o un gruppo e un ruolo.",
      'Un progetto deve avere sempre almeno un proprietario. I gruppi sono gestiti dagli amministratori in Impostazioni e possono essere sincronizzati con il single sign-on.',
    ],
    shots: [{ file: 'share-dialog', alt: 'La finestra Condividi' }],
  },
  {
    id: 'project',
    title: 'Impostazioni del progetto',
    icon: 'tune',
    intro: [
      'I proprietari di un progetto aprono Impostazioni del progetto dal suo menu. La policy dei provider sceglie quali provider di modelli possono ricevere i contenuti del progetto (documenti, domande, immagini): tutti quelli configurati, oppure solo quelli selezionati, per esempio un unico provider di fiducia per materiale riservato. Senza alcun provider selezionato, nel progetto non si può indicizzare né rispondere.',
      "La stessa finestra mostra l'indice di ricerca e quale modello di embedding serve le ricerche.",
    ],
    shots: [{ file: 'project-settings', alt: 'Impostazioni del progetto' }],
  },
  {
    id: 'models',
    title: 'Modelli e provider (amministratori)',
    icon: 'settings',
    intro: [
      'In Impostazioni → Provider un amministratore aggiunge i provider esterni (chiave API, eventuale URL di base), sincronizza i cataloghi dei modelli e abilita quelli da usare. Le chiavi sono salvate cifrate e non vengono più mostrate. Usa Prova accanto a un modello per verificare che funzioni.',
      'In Impostazioni → Modelli ogni fase ha una catena di modelli: chat, riassunti, estrazione del grafo, descrizione delle immagini, OCR, embedding e riordino facoltativo. Si usa il primo modello, i successivi sono di riserva. Un progetto può sostituire la catena globale. Cambiare il modello di embedding richiede di re-indicizzare le fonti.',
      "Impostazioni → Utenti e Gruppi creano account e gruppi; l'accesso vero e proprio si concede dall'albero del Workbench.",
    ],
    shots: [
      { file: 'settings-models', alt: 'Le catene di modelli per fase' },
      { file: 'settings-providers', alt: "L'elenco dei provider" },
    ],
  },
  {
    id: 'status',
    title: 'Stato RAG',
    icon: 'monitor_heart',
    intro: [
      "Lo Stato RAG mostra la salute dei servizi, quante fonti ci sono in ogni stato, le code, l'indice per progetto (modello di embedding, fonti, chunk) e gli ultimi job. Le fonti non riuscite sono elencate con il motivo e un pulsante Riprova.",
      'Usa Re-indicizza quando cambi il modello di embedding (chiama il provider per ogni chunk) e Ricostruisci il grafo per estrarre di nuovo il knowledge graph.',
    ],
    shots: [{ file: 'status', alt: 'La pagina Stato RAG' }],
  },
  {
    id: 'help',
    title: 'Risoluzione dei problemi',
    icon: 'help',
    intro: ['Situazioni comuni e cosa fare.'],
    tips: [
      'Una fonte resta non riuscita con «servono un OCR o un modello di visione»: chiedi a un amministratore di assegnarne uno in Impostazioni → Modelli, poi premi Riprova o Re-indicizza.',
      "Una risposta dice che l'informazione non è stata trovata: controlla che le fonti siano attive, che l'ambito le contenga e che siano pronte; prova il pannello Cerca per vedere cosa viene recuperato.",
      'Le citazioni aprono il visualizzatore di testo invece del PDF: il file è un DOCX, XLSX o simile e non è configurato il servizio di conversione; il testo è lo stesso.',
      'Le pagine web che costruiscono il contenuto con JavaScript rendono poco testo; salva la pagina in PDF e caricala.',
      'Un messaggio sul limite di ricerche approfondite significa che la quota oraria è esaurita; attendi e riprova.',
    ],
  },
];

export const GUIDE: Record<Lang, GuideSection[]> = { en: EN, it: IT };
