import os
import sys
import time
import traceback
from PIL import Image, ImageDraw, ImageFont

# Force disable Numba caching to prevent ReferenceError: underlying object has vanished
os.environ["NUMBA_DISABLE_CACHING"] = "1"
# Also try setting a local cache dir just in case
os.environ["NUMBA_CACHE_DIR"] = os.path.join(os.getcwd(), ".numba_cache")

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.fractal_renderer import FractalShadesRenderer

OUTPUT_DIR = "artifacts/gallery_v2"

GALLERY_ITEMS = [
    {
        "title": "1. Glossy Seahorse",
        "desc": "Mandelbrot with 3D lighting",
        "filename": "01_seahorse_glossy.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-0.746223962861", "y": "-0.0959468433527", "dx": "0.00745",
            "nx": 400, "max_iter": 2000,
            "shade_kind": "glossy",
            "lighting_config": {
                "k_diffuse": 0.4, "k_specular": 30.0, "shininess": 400.0,
                "polar_angle": 135.0, "azimuth_angle": 20.0,
                "gloss_light_color": [1.0, 0.9, 0.9]
            },
            "colormap": "legacy"
        }
    },
    {
        "title": "2. Twin Fieldlines",
        "desc": "Mandelbrot with fieldlines",
        "filename": "02_fieldlines_twin.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-0.1065", "y": "0.9695", "dx": "0.7",
            "nx": 400, "max_iter": 1000,
            "fieldlines_kind": "twin",
            "fieldlines_func": {"n_iter": 4, "swirl": 0.0, "twin_intensity": 0.5},
            "colormap": "ocean"
        }
    },
    {
        "title": "3. Double Embedded Julia",
        "desc": "Perturbation Mandelbrot with twin fieldlines",
        "filename": "03_double_embedded_julia.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-1.768667862837488812627419470",
            "y": "0.001645580546820209430325900",
            "dx": "12.e-22",
            "nx": 400, "max_iter": 20000, "precision": 30,
            "shade_kind": "glossy",
            "colormap": "classic",
            "base_layer": "continuous_iter",
            "zmin": 9.015, "zmax": 9.025,
            "fieldlines_kind": "twin",
            "fieldlines_func": {"n_iter": 3, "swirl": 0.0, "endpoint_k": 1.0, "twin_intensity": 0.0005},
            "lighting_config": {
                "k_diffuse": 0.4, "k_specular": 10.0, "shininess": 400.0,
                "polar_angle": 45.0, "azimuth_angle": 20.0,
                "gloss_light_color": [0.9, 0.9, 0.9]
            }
        }
    },
    {
        "title": "4. Burning Ship Deep",
        "desc": "BS deep zoom with skew",
        "filename": "04_burning_ship_deep.png",
        "params": {
            "fractal_type": "burning_ship",
            "x": "0.533551593577038561769721161491702555962775680136595415306315189524970818968817900068355227861158570104764433694",
            "y": "1.26175074578870311547721223871955368990255513054155186351034363459852900933566891849764050954410207620093433856",
            "dx": "7.072814368784043e-101",
            "nx": 400, "max_iter": 5000, "precision": 150,
            "xy_ratio": 1.8, "theta_deg": -2.0,
            "skew_params": {
                "skew_00": 1.3141410612942215, "skew_01": 0.8651590600810832,
                "skew_10": 0.6372176654581702, "skew_11": 1.1804627997751416
            },
            "base_layer": "distance_estimation",
            "colormap": "dawn",
            # Fixed: Added probes from example 14
            "zmin": -9.90, "zmax": -4.94
        }
    },
    {
        "title": "5. Perp. Burning Ship",
        "desc": "Glynn Spiral (Hidden)",
        "filename": "05_perp_bs_glynn.png",
        "params": {
            "fractal_type": "perpendicular_burning_ship",
            "flavor": "Perpendicular burning ship",
            "x": "-1.6221172452279831275586824847368230989301274844265",
            "y": "-0.0043849065564689427951877101597546609652950526531633",
            "dx": "4.646303299697506e-40",
            "nx": 400, "max_iter": 20000, "precision": 55,
            "xy_ratio": 1.8, "theta_deg": -2.0,
            "skew_params": {
                "skew_00": 1.011753723519244, "skew_01": -1.157539989768796,
                "skew_10": -0.5299787188179303, "skew_11": 1.5947275737676074
            },
            "base_layer": "distance_estimation",
            "shade_kind": "glossy",
            "colormap": "peacock",
            # Fixed: Added probes from example 18
            "zmin": 6.54, "zmax": 18.42
        }
    },
    {
        "title": "6. Perp. BS Sierpinski",
        "desc": "Sierpinski Carpets",
        "filename": "06_perp_bs_sierpinski.png",
        "params": {
            "fractal_type": "perpendicular_burning_ship",
            "flavor": "Perpendicular burning ship",
            "x": "-1.929319698524937920226708049698305350754670432084006734339806946",
            "y": "-0.0000000000000000007592779387989739090287550144163328879329853232537252481600401185",
            "dx": "7.032184999234219e-55",
            "nx": 400, "max_iter": 20000, "precision": 64,
            "xy_ratio": 1.6, "theta_deg": -26.0,
            "skew_params": {
                "skew_00": 1.05, "skew_01": 0.0,
                "skew_10": -0.1, "skew_11": 0.9523809
            },
            "shade_kind": "glossy",
            "base_layer": "distance_estimation",
            "colormap": "hot",
            # Fixed: Added probes from example 20
            "zmin": 8.71, "zmax": 9.90
        }
    },
    {
        "title": "7. Perp. BS Trees",
        "desc": "Tree structures",
        "filename": "07_perp_bs_trees.png",
        "params": {
            "fractal_type": "perpendicular_burning_ship",
            "flavor": "Perpendicular burning ship",
            "x": "-1.60075649116104853234447567671822519294",
            "y": "-0.00000585584069328913182973043272000146363667",
            "dx": "1.345424030679299e-29",
            "nx": 400, "max_iter": 6000, "precision": 64,
            "xy_ratio": 1.6, "theta_deg": 120.0,
            "skew_params": {
                "skew_00": -0.985244568474214, "skew_01": 0.6137988525,
                "skew_10": 0.8089497623371, "skew_11": -1.518945126681
            },
            "shade_kind": "glossy",
            "colormap": "spring",
            # Added probes from example 21 just in case, though previous run was okay
            "zmin": 7.51, "zmax": 8.06
        }
    },
    {
        "title": "8. Shark Fin",
        "desc": "Shark Fin flavor",
        "filename": "08_shark_fin.png",
        "params": {
            "fractal_type": "shark_fin",
            "flavor": "Shark fin",
            "x": "-0.5", "y": "-0.65", "dx": "0.5", 
            "nx": 400, "max_iter": 1500,
            "colormap": "blue_brown"
        }
    },
    {
        "title": "9. PerturbDeep Embedded Julia",
        "desc": "Ultra-deep perturbation zoom (downscaled)",
        "filename": "09_perturbdeep_embedded_julia.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-1.9409989391128007782656638595713128206620929316331395903205283705275932149841553750079140508152501109445961064000387852149507811657094626324996392008081820445955741490587617909708619603737265548027769325647808985287741667276189821676033432683374240723052323372896622554689290278821522432095519048328761094875168059910075072612524746195696519482376711787954155676296696827707057348137590781477540653443160271404114741216279924299516050033371623738987930710049260335938454436747992050897445704854917586460267198917634232454874517524790905068408711299098852857223323363509317448492707948571935557902448516804312250656708860690680767226144394692148838449346680921087412029850014210409147937112323614271639154365986968749816836442985665512979922489943829925482859841402388822224364772960765860128299173467963835512792813373451933644130190266047607001031626499249499592567711348988794983423352102489653363614657987130851011066068082416311059571884201802812522326939248656260215898332770887339844184688424916821959905805787211079924762420560654209080231130357236288188593275206143270109163936044056855567309338390204460230556526667618113052517191169646813610992208066490740332700166077086244561644939752386971282938070707062898838928187674154565542324706485606883204149973662143729325062503353762046809254607154103878222668282005954040495000651634097511941293052468376780564225465557438420172736278899353415715205080501056910932380856513690069593717239355697113322999606963893343303065997244593517188694362601778555657829079220370979486386183376634551544169026880446433151630826730127399985709844229666877539084763034446297595098204169627029966553348731711298433915468877133916519870332995252770006087468201433091412692008675169426600509762262849033820684824479730400854046509072164630272105114166613615665383021053646289448207336461725630828678598527683609575006544933462912457658924436663804582292428129309162915840098216747977268766925226272677267826315722555021136934491464926926641085339160830952887601459585519624489323898936587933143756193630971066578717659019875144049965572880866540996031144922280813352065159362962936897218127976473669535727210317367178865163942427120257230318803642220091013441782124465936161868040076934432584798273802125003893761405910549636791922164569969871504895180875775512279622397659490539731258965222183682582044022842758452337516752189727551206382556078493830490372988205049395299138260871313038171904760429268109644267193074206275040851482988811238053209498575928806745490180665861235757156293268030156174736154214485511919238045324816790747039434094153238651378208655247035749519428374239948111490578363711926298127059816373882058600875440218265729937727712935557101248183859985480838214443248343204994169001603385068217409551664275124868238925925271002064990910751541295196946319404974130124223074815816387748372081603618046256402766723419509314015491326315372861880224396707850752490829513864536227468094212074909783507683557390914984737208904927522859784984066452431380596052384391155762961147112917902257288838205513568126100751182438074841839964967562205987620459771593676482435160564881907643374624834394770129519338651384779340621276744712596399177749754956987947612707663018919330037816063293842647052555147743226921275393227281792532802856285703297338604821969492356674112869979073125870095512233460880231177088317720580337642382172126187069216048936896730950168087435988621276438670059341103609929304930466412268150569753470717829497601938341623581803667066999928999945000062",
            "y": "-0.0006521165369165588520106289441620153907907521525225557951700039268755659160275378414816331241993503713942651869474366440330624054932785747734116130598457275168672169867853790149073948820621927863546898987531675745541556010963860271946131945706089440068213570737152573434606181998626256475661137064241766615685133034114571184540746713081041577482152866404680905298142203271097108866125320734562827910017740404764291477614758081664091324083106696109319507742512146578699926177581123430550120851818916049981949393089874937840577370413575565615246397463453690404270526656455145637869566754373564864548747775061651693403960187403612827482714675143082173905414385810506804378880397100996175280822311114495867725750471436402145707242763362689139153766093202506743259707579782531683072699910204376229255257696447791057044885184061849070063540925613028401048182129422816270970456315092465855569329878796473503666036123284601909076758201573065328180211040459230345709044071756847669905912521106047214804555579992552727318466143562534207465701332898411609149336015158023746864705973770293526683875460324480616782478489019514943512702395590818455582259983339029054638765126731537575594335734368117123722683120375030995584809981966023016675121788001130361752945926045051983789243281329028107416493849599211739205918880442308088915329310667744587253842928202077978689211781621700292204988439971992046135099101850443216579189710924423016693808479474589682525790322932538431715348758724089186172736870724706725359784401019519888555644853285575115223472590818823322033130852641478536530503881747200363162574382337579455223211205019832848615171631087121056343365803496414693646695845027511119821045191586941544022389773784151557473277272394880876628653639136977979073123486169650096416150642999247909147333278062324113459547152270378118487801961875006181455991513879900323624590458328414797373565255061007383050772917420374420930369627261609756033085579925058681478773760867701230719359928389502388023578804808713069253869301107296738982313988108484002367456921622985540672687977893371677916030176767500564905285025226973308704535270965189005321129735333599100313629076978281635241128387571784303118677495016595486491171040002394480779899042204488631259847989603182340726213078367178896618081990169319498713349339065257474424401748553283927933449943175175157120972516636257833849555669271463331231601029167028638597915809746995436188809835668111701784052366810307436108276491541042658178481843136392746657892940367221519240125914939061964441432380740020708127640600546604568699045234845708728863090863984386209155813013615576381026653379878624402126265227089167061378994809588030662831377110537145242600584959148498586439529663105983709419546957848439948376427305067215182145348517650481959560955434577158090652441197554228656503253796471623707876797570793456353888545895776536724341010890647565137237971578364800606022054805371016117249815862385204930532791360055457643453800167233033393824944921504096748637258867979270585206447548364249344195079436376739232814985700753366335710763351616828921383429188346008648781525793755795069682228036514982477038907976343304196109685257025904974333612600761354191140826329760186432247441069680365217200145218033541210372615053282512008534408785235009976598833958899392833195540809260984815364215770028371283427130718815533338521166040923413722562752702386025562655776477893889452984598715385588865771230862335806477085969230662862126372402082027768431991530300520064005268033000000000000000000",
            # Adjusted to a renderable depth while preserving the example's location.
            # The full ultra-deep dx=2.e-2608 needs chained-bivariate approximations
            # not exposed by our generic renderer, and rendered black.
            "dx": "2.e-20",
            "nx": 400, "max_iter": 20000, "precision": 120,
            "xy_ratio": 1.7777777778,
            "shade_kind": "standard",
            "colormap": "atoll",
            "base_layer": "continuous_iter",
            "interior_mask": "not_diverging",
            "lighting_config": {
                "k_diffuse": 0.5, "k_specular": 400.0, "shininess": 400.0,
                "polar_angle": 60.0, "azimuth_angle": 20.0,
                "color": [0.5, 0.5, 0.4]
            }
        }
    },
    {
        "title": "10. Multibrot Power 4",
        "desc": "Mandelbrot N=4",
        "filename": "10_multibrot_p4.png",
        "params": {
            "fractal_type": "mandelbrot_n",
            "exponent": 4,
            "x": "0.0", "y": "0.0", "dx": "2.5",
            "nx": 400, "max_iter": 1500,
            "colormap": "autumn"
        }
    }
]

def create_composite_gallery(items, output_path):
    """Creates a labeled grid image of all fractals."""
    print("\nGenerating composite gallery image...")
    
    cols = 5
    rows = (len(items) + cols - 1) // cols
    
    # Config
    tile_w, tile_h = 400, 300 # Resize for grid
    padding = 20
    text_h = 80
    
    full_w = cols * tile_w + (cols + 1) * padding
    full_h = rows * (tile_h + text_h) + (rows + 1) * padding
    
    bg_color = (20, 20, 20)
    text_color = (220, 220, 220)
    
    gallery_img = Image.new("RGB", (full_w, full_h), bg_color)
    draw = ImageDraw.Draw(gallery_img)
    
    # Try to load a font
    try:
        # Mac default
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except:
        try:
            # Linux default
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

    for i, item in enumerate(items):
        r, c = divmod(i, cols)
        
        # Load and resize image
        img_path = os.path.join(OUTPUT_DIR, item["filename"])
        try:
            with Image.open(img_path) as img:
                # Resize preserving aspect ratio logic could go here, but strict resize is easier for grid
                # We generated them at 800x? depending on ratio. Let's crop/resize to fit tile
                img = img.convert("RGB")
                img.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
                
                # Paste coordinates
                x_off = padding + c * (tile_w + padding)
                y_off = padding + r * (tile_h + text_h + padding)
                
                # Center image in slot
                paste_x = x_off + (tile_w - img.width) // 2
                paste_y = y_off + (tile_h - img.height) // 2
                
                gallery_img.paste(img, (paste_x, paste_y))
                
                # Draw text
                text_y = y_off + tile_h + 5
                draw.text((x_off, text_y), item["title"], font=font, fill=text_color)
                draw.text((x_off, text_y + 20), item["desc"], font=font_small, fill=(150, 150, 150))
                duration = item.get("duration_s")
                if duration is not None:
                    draw.text((x_off, text_y + 40), f"Time: {duration:.2f}s", font=font_small, fill=(120, 200, 120))
                
        except Exception as e:
            print(f"Failed to process image {item['filename']}: {e}")

    gallery_img.save(output_path)
    print(f"Gallery saved to: {output_path}")

def run_gallery():
    print(f"Generating diverse gallery in: {OUTPUT_DIR}")
    # Ensure cache dir exists
    os.makedirs(os.environ["NUMBA_CACHE_DIR"], exist_ok=True)
    
    renderer = FractalShadesRenderer(OUTPUT_DIR)
    start_time = time.time()
    
    successful_items = []

    for item in GALLERY_ITEMS:
        print(f"\nRendering {item['title']}...")
        try:
            t0 = time.time()
            renderer.render(filename=item["filename"], supersampling="None", **item["params"])
            duration = time.time() - t0
            item_with_duration = dict(item)
            item_with_duration["duration_s"] = duration
            successful_items.append(item_with_duration)
        except Exception as e:
            print(f"❌ Error rendering {item['title']}: {e}")
            traceback.print_exc()

    duration = time.time() - start_time
    print(f"\nAll renders complete in {duration:.2f}s")
    
    if successful_items:
        composite_path = os.path.join(OUTPUT_DIR, "fractal_gallery_composite.png")
        create_composite_gallery(successful_items, composite_path)

if __name__ == "__main__":
    run_gallery()
